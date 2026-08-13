from collections.abc import Iterable
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any

import psycopg
from psycopg.rows import dict_row

from colorslice.color import (
    circular_distance,
    noise_filtered_histogram,
    rank_score,
    salient_slice_coverage,
    salient_slices_coverage,
    slice_breadth,
    slice_presence,
    slices_breadth,
)
from colorslice.models import Artwork, ArtworkMatch, ArtworkRecord, HUE_BIN_COUNT


CATALOG_PROFILE_VERSION = 2
MINIMUM_SECTION_PRESENCE = 0.02
MINIMUM_RAW_SECTION_PRESENCE = 0.01
ZERO_HUE_MASK = "0" * HUE_BIN_COUNT


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS artworks (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    year INTEGER,
    image_url TEXT NOT NULL,
    thumbnail_url TEXT NOT NULL,
    source_url TEXT NOT NULL,
    license_label TEXT NOT NULL,
    hue_histogram TEXT NOT NULL,
    area_hue_histogram TEXT NOT NULL,
    dominant_hue REAL NOT NULL,
    colorfulness REAL NOT NULL,
    hue_mask TEXT,
    area_hue_mask TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, source_id)
);
CREATE INDEX IF NOT EXISTS artworks_source_idx ON artworks(source);
CREATE INDEX IF NOT EXISTS artworks_hue_idx ON artworks(dominant_hue);
CREATE TABLE IF NOT EXISTS catalog_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS artworks (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    year INTEGER,
    image_url TEXT NOT NULL,
    thumbnail_url TEXT NOT NULL,
    source_url TEXT NOT NULL,
    license_label TEXT NOT NULL,
    hue_histogram JSONB NOT NULL,
    area_hue_histogram JSONB NOT NULL,
    dominant_hue DOUBLE PRECISION NOT NULL,
    colorfulness DOUBLE PRECISION NOT NULL,
    hue_mask BIT(72),
    area_hue_mask BIT(72),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(source, source_id)
);
CREATE INDEX IF NOT EXISTS artworks_source_idx ON artworks(source);
CREATE INDEX IF NOT EXISTS artworks_hue_idx ON artworks(dominant_hue);
CREATE TABLE IF NOT EXISTS catalog_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

POSTGRES_AREA_HISTOGRAM_MIGRATION = """
ALTER TABLE artworks ADD COLUMN IF NOT EXISTS area_hue_histogram JSONB;
UPDATE artworks
SET area_hue_histogram = hue_histogram
WHERE area_hue_histogram IS NULL;
ALTER TABLE artworks ALTER COLUMN area_hue_histogram SET NOT NULL;
ALTER TABLE artworks ADD COLUMN IF NOT EXISTS hue_mask BIT(72);
ALTER TABLE artworks ADD COLUMN IF NOT EXISTS area_hue_mask BIT(72);
"""

POSTGRES_UPSERT = """
INSERT INTO artworks (
    id, source, source_id, title, artist, year, image_url,
    thumbnail_url, source_url, license_label, hue_histogram,
    area_hue_histogram, dominant_hue, colorfulness, hue_mask,
    area_hue_mask
) VALUES (
    %(id)s, %(source)s, %(source_id)s, %(title)s, %(artist)s, %(year)s,
    %(image_url)s, %(thumbnail_url)s, %(source_url)s, %(license_label)s,
    %(hue_histogram)s::jsonb, %(area_hue_histogram)s::jsonb,
    %(dominant_hue)s, %(colorfulness)s, %(hue_mask)s::bit(72),
    %(area_hue_mask)s::bit(72)
)
ON CONFLICT (id) DO UPDATE SET
    title = EXCLUDED.title,
    artist = EXCLUDED.artist,
    year = EXCLUDED.year,
    image_url = EXCLUDED.image_url,
    thumbnail_url = EXCLUDED.thumbnail_url,
    source_url = EXCLUDED.source_url,
    license_label = EXCLUDED.license_label,
    hue_histogram = EXCLUDED.hue_histogram,
    area_hue_histogram = EXCLUDED.area_hue_histogram,
    dominant_hue = EXCLUDED.dominant_hue,
    colorfulness = EXCLUDED.colorfulness,
    hue_mask = EXCLUDED.hue_mask,
    area_hue_mask = EXCLUDED.area_hue_mask
"""


def _histogram_mask(histogram: tuple[float, ...]) -> str:
    filtered = noise_filtered_histogram(histogram)
    return "".join("1" if weight > 0.0 else "0" for weight in filtered)


def _selected_mask(sections: tuple[tuple[float, float], ...]) -> str:
    bin_width = 360.0 / HUE_BIN_COUNT
    return "".join(
        "1"
        if any(
            circular_distance((index + 0.5) * bin_width, center) <= span / 2.0
            for center, span in sections
        )
        else "0"
        for index in range(HUE_BIN_COUNT)
    )


def sqlite_artwork_count(path: Path) -> int:
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM artworks").fetchone()
    return int(row[0]) if row else 0


class ArtworkRepository:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.environ.get("DATABASE_URL")
        if os.environ.get("VERCEL"):
            default_path = Path("/tmp/colorslice.db")
            bundled_seed = Path(__file__).resolve().parent.parent / "data/seed.db"
            if not default_path.exists() and bundled_seed.exists():
                shutil.copyfile(bundled_seed, default_path)
        else:
            default_path = Path("data/colorslice.db")
        self.sqlite_path = Path(os.environ.get("COLORSLICE_DB_PATH", default_path))
        self.is_postgres = bool(
            self.database_url
            and self.database_url.startswith(("postgres://", "postgresql://"))
        )
        self.exact_masks_ready = False

    @contextmanager
    def _connection(self):
        if self.is_postgres:
            if self.database_url is None:
                raise RuntimeError("Postgres connection URL is missing")
            with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
                yield connection
            return

        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.sqlite_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connection() as connection:
            if self.is_postgres:
                with connection.cursor() as cursor:
                    cursor.execute(POSTGRES_SCHEMA)
                    cursor.execute(POSTGRES_AREA_HISTOGRAM_MIGRATION)
            else:
                connection.executescript(SQLITE_SCHEMA)
                columns = {
                    str(row["name"])
                    for row in connection.execute("PRAGMA table_info(artworks)")
                }
                if "area_hue_histogram" not in columns:
                    connection.execute(
                        "ALTER TABLE artworks ADD COLUMN area_hue_histogram TEXT"
                    )
                if "hue_mask" not in columns:
                    connection.execute("ALTER TABLE artworks ADD COLUMN hue_mask TEXT")
                if "area_hue_mask" not in columns:
                    connection.execute(
                        "ALTER TABLE artworks ADD COLUMN area_hue_mask TEXT"
                    )
                connection.execute(
                    """
                    UPDATE artworks
                    SET area_hue_histogram = hue_histogram
                    WHERE area_hue_histogram IS NULL
                    """
                )
            connection.commit()
            missing_masks = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM artworks
                WHERE hue_mask IS NULL OR area_hue_mask IS NULL
                """
            ).fetchone()
            self.exact_masks_ready = (
                missing_masks is not None
                and int(dict(missing_masks)["count"]) == 0
            )

    def catalog_profile_version(self) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM catalog_metadata WHERE key = 'profile_version'"
            ).fetchone()
        return int(dict(row)["value"]) if row is not None else 1

    def set_catalog_profile_version(self, version: int) -> None:
        with self._connection() as connection:
            placeholder = "%s" if self.is_postgres else "?"
            connection.execute(
                f"""
                INSERT INTO catalog_metadata (key, value)
                VALUES ('profile_version', {placeholder})
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (str(version),),
            )
            connection.commit()

    def seed_from_sqlite(self, source_path: Path) -> dict[str, int]:
        if not self.is_postgres:
            raise RuntimeError("Postgres is required for catalog seeding")
        if not source_path.exists():
            raise FileNotFoundError(source_path)

        with sqlite3.connect(source_path) as source:
            source.row_factory = sqlite3.Row
            rows = [dict(row) for row in source.execute("SELECT * FROM artworks")]

        for row in rows:
            hue_histogram = tuple(
                float(value) for value in json.loads(row["hue_histogram"])
            )
            area_hue_histogram = tuple(
                float(value) for value in json.loads(row["area_hue_histogram"])
            )
            row["hue_mask"] = _histogram_mask(hue_histogram)
            row["area_hue_mask"] = _histogram_mask(area_hue_histogram)

        with self._connection() as destination:
            with destination.cursor() as cursor:
                cursor.executemany(POSTGRES_UPSERT, rows)
            destination.commit()
        return self.source_counts()

    def upsert(
        self,
        record: ArtworkRecord,
        hue_histogram: tuple[float, ...],
        area_hue_histogram: tuple[float, ...],
        dominant_hue: float,
        colorfulness: float,
    ) -> None:
        self.upsert_many(
            [
                (
                    record,
                    hue_histogram,
                    area_hue_histogram,
                    dominant_hue,
                    colorfulness,
                )
            ]
        )

    def upsert_many(
        self,
        entries: list[
            tuple[
                ArtworkRecord,
                tuple[float, ...],
                tuple[float, ...],
                float,
                float,
            ]
        ],
    ) -> None:
        values = []
        for (
            record,
            hue_histogram,
            area_hue_histogram,
            dominant_hue,
            colorfulness,
        ) in entries:
            if len(hue_histogram) != HUE_BIN_COUNT:
                raise ValueError(f"Expected {HUE_BIN_COUNT} hue bins")
            if len(area_hue_histogram) != HUE_BIN_COUNT:
                raise ValueError(f"Expected {HUE_BIN_COUNT} area hue bins")
            values.append(
                (
                    record.id,
                    record.source,
                    record.source_id,
                    record.title,
                    record.artist,
                    record.year,
                    record.image_url,
                    record.thumbnail_url,
                    record.source_url,
                    record.license_label,
                    json.dumps(hue_histogram),
                    json.dumps(area_hue_histogram),
                    dominant_hue,
                    colorfulness,
                    _histogram_mask(hue_histogram),
                    _histogram_mask(area_hue_histogram),
                )
            )
        if not values:
            return

        with self._connection() as connection:
            if self.is_postgres:
                query = """
                    INSERT INTO artworks (
                        id, source, source_id, title, artist, year, image_url,
                        thumbnail_url, source_url, license_label, hue_histogram,
                        area_hue_histogram, dominant_hue, colorfulness,
                        hue_mask, area_hue_mask
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, %s, %s, %s::bit(72), %s::bit(72)
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        artist = EXCLUDED.artist,
                        year = EXCLUDED.year,
                        image_url = EXCLUDED.image_url,
                        thumbnail_url = EXCLUDED.thumbnail_url,
                        source_url = EXCLUDED.source_url,
                        license_label = EXCLUDED.license_label,
                        hue_histogram = EXCLUDED.hue_histogram,
                        area_hue_histogram = EXCLUDED.area_hue_histogram,
                        dominant_hue = EXCLUDED.dominant_hue,
                        colorfulness = EXCLUDED.colorfulness,
                        hue_mask = EXCLUDED.hue_mask,
                        area_hue_mask = EXCLUDED.area_hue_mask
                """
            else:
                query = """
                    INSERT INTO artworks (
                        id, source, source_id, title, artist, year, image_url,
                        thumbnail_url, source_url, license_label, hue_histogram,
                        area_hue_histogram, dominant_hue, colorfulness,
                        hue_mask, area_hue_mask
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        artist = excluded.artist,
                        year = excluded.year,
                        image_url = excluded.image_url,
                        thumbnail_url = excluded.thumbnail_url,
                        source_url = excluded.source_url,
                        license_label = excluded.license_label,
                        hue_histogram = excluded.hue_histogram,
                        area_hue_histogram = excluded.area_hue_histogram,
                        dominant_hue = excluded.dominant_hue,
                        colorfulness = excluded.colorfulness,
                        hue_mask = excluded.hue_mask,
                        area_hue_mask = excluded.area_hue_mask
                """
            if self.is_postgres:
                with connection.cursor() as cursor:
                    cursor.executemany(query, values)
            else:
                connection.executemany(query, values)
            connection.commit()

    def all_artworks(self) -> list[Artwork]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, source, source_id, title, artist, year, image_url,
                       thumbnail_url, source_url, license_label, hue_histogram,
                       area_hue_histogram, dominant_hue, colorfulness
                FROM artworks
                ORDER BY id
                """
            ).fetchall()
        return [Artwork.from_mapping(dict(row)) for row in rows]

    def existing_record_source_ids(
        self,
        records: list[ArtworkRecord],
    ) -> set[str]:
        if not records:
            return set()
        source = records[0].source
        if any(record.source != source for record in records):
            raise ValueError("All records must use the same source")

        placeholder = "%s" if self.is_postgres else "?"
        source_ids = tuple(record.source_id for record in records)
        image_urls = tuple(record.image_url for record in records)
        source_id_placeholders = ", ".join(placeholder for _ in source_ids)
        image_url_placeholders = ", ".join(placeholder for _ in image_urls)
        query = f"""
            SELECT source_id, image_url
            FROM artworks
            WHERE source = {placeholder}
              AND (
                source_id IN ({source_id_placeholders})
                OR image_url IN ({image_url_placeholders})
              )
        """
        with self._connection() as connection:
            rows = connection.execute(
                query,
                (source, *source_ids, *image_urls),
            ).fetchall()

        existing_source_ids = {str(dict(row)["source_id"]) for row in rows}
        existing_image_urls = {str(dict(row)["image_url"]) for row in rows}
        return {
            record.source_id
            for record in records
            if record.source_id in existing_source_ids
            or record.image_url in existing_image_urls
        }

    def backfill_missing_masks(self, batch_size: int = 1_000) -> tuple[int, int]:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        placeholder = "%s" if self.is_postgres else "?"
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT id, hue_histogram, area_hue_histogram
                FROM artworks
                WHERE hue_mask IS NULL OR area_hue_mask IS NULL
                ORDER BY id
                LIMIT {placeholder}
                """,
                (batch_size,),
            ).fetchall()
            updates = []
            for row in rows:
                values = dict(row)
                raw_hue = values["hue_histogram"]
                raw_area = values["area_hue_histogram"]
                hue_values = json.loads(raw_hue) if isinstance(raw_hue, str) else raw_hue
                area_values = (
                    json.loads(raw_area) if isinstance(raw_area, str) else raw_area
                )
                updates.append(
                    (
                        _histogram_mask(tuple(float(value) for value in hue_values)),
                        _histogram_mask(tuple(float(value) for value in area_values)),
                        str(values["id"]),
                    )
                )

            if updates:
                if self.is_postgres:
                    with connection.cursor() as cursor:
                        cursor.executemany(
                            """
                            UPDATE artworks
                            SET hue_mask = %s::bit(72), area_hue_mask = %s::bit(72)
                            WHERE id = %s
                            """,
                            updates,
                        )
                else:
                    connection.executemany(
                        """
                        UPDATE artworks
                        SET hue_mask = ?, area_hue_mask = ?
                        WHERE id = ?
                        """,
                        updates,
                    )
            missing = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM artworks
                WHERE hue_mask IS NULL OR area_hue_mask IS NULL
                """
            ).fetchone()
            connection.commit()

        remaining = int(dict(missing)["count"]) if missing is not None else 0
        self.exact_masks_ready = remaining == 0
        return len(updates), remaining

    def update_profiles(
        self,
        updates: list[
            tuple[
                str,
                tuple[float, ...],
                tuple[float, ...],
                float,
                float,
            ]
        ],
    ) -> None:
        values = []
        for artwork_id, histogram, area_histogram, dominant_hue, colorfulness in updates:
            if len(histogram) != HUE_BIN_COUNT:
                raise ValueError(f"Expected {HUE_BIN_COUNT} hue bins")
            if len(area_histogram) != HUE_BIN_COUNT:
                raise ValueError(f"Expected {HUE_BIN_COUNT} area hue bins")
            values.append(
                (
                    json.dumps(histogram),
                    json.dumps(area_histogram),
                    dominant_hue,
                    colorfulness,
                    _histogram_mask(histogram),
                    _histogram_mask(area_histogram),
                    artwork_id,
                )
            )
        if not values:
            return

        with self._connection() as connection:
            if self.is_postgres:
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """
                        UPDATE artworks
                        SET hue_histogram = %s::jsonb,
                            area_hue_histogram = %s::jsonb,
                            dominant_hue = %s,
                            colorfulness = %s,
                            hue_mask = %s::bit(72),
                            area_hue_mask = %s::bit(72)
                        WHERE id = %s
                        """,
                        values,
                    )
            else:
                connection.executemany(
                    """
                    UPDATE artworks
                    SET hue_histogram = ?,
                        area_hue_histogram = ?,
                        dominant_hue = ?,
                        colorfulness = ?,
                        hue_mask = ?,
                        area_hue_mask = ?
                    WHERE id = ?
                    """,
                    values,
                )
            connection.commit()

    def _fetch_candidates(
        self,
        center: float,
        span: float,
        sources: tuple[str, ...],
        candidate_limit: int = 10_000,
    ) -> list[Artwork]:
        source_values = sources or ("magic", "met")
        broad_span = min(180.0, span / 2.0 + 55.0)
        clauses = []
        parameters: list[Any] = []
        for source in source_values:
            clauses.append("source = %s" if self.is_postgres else "source = ?")
            parameters.append(source)
        source_clause = " OR ".join(clauses)

        placeholder = "%s" if self.is_postgres else "?"
        query = f"""
            SELECT id, source, source_id, title, artist, year, image_url,
                   thumbnail_url, source_url, license_label, hue_histogram,
                   area_hue_histogram, dominant_hue, colorfulness
            FROM artworks
            WHERE ({source_clause})
              AND (
                ABS(dominant_hue - {placeholder}) <= {placeholder}
                OR ABS(dominant_hue - {placeholder}) >= {placeholder}
              )
            ORDER BY colorfulness DESC
            LIMIT {placeholder}
        """
        parameters.extend((center, broad_span, center, 360.0 - broad_span, candidate_limit))
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [Artwork.from_mapping(dict(row)) for row in rows]

    def _fetch_exact_candidates(
        self,
        sections: tuple[tuple[float, float], ...],
        sources: tuple[str, ...],
        candidate_limit: int = 50_000,
    ) -> list[Artwork]:
        if not self.is_postgres:
            raise RuntimeError("Exact mask search requires Postgres")

        source_values = sources or ("magic", "met")
        source_clause = " OR ".join("source = %s" for _ in source_values)
        selected = _selected_mask(sections)
        outside = "".join("0" if bit == "1" else "1" for bit in selected)
        presence_masks = [_selected_mask((section,)) for section in sections]
        presence_clauses = "\n".join(
            "AND (hue_mask & %s::bit(72)) <> %s::bit(72)"
            for _ in presence_masks
        )
        query = f"""
            SELECT id, source, source_id, title, artist, year, image_url,
                   thumbnail_url, source_url, license_label, hue_histogram,
                   area_hue_histogram, dominant_hue, colorfulness
            FROM artworks
            WHERE ({source_clause})
              AND hue_mask IS NOT NULL
              AND area_hue_mask IS NOT NULL
              AND (hue_mask & %s::bit(72)) = %s::bit(72)
              AND (area_hue_mask & %s::bit(72)) = %s::bit(72)
              {presence_clauses}
            ORDER BY colorfulness DESC
            LIMIT %s
        """
        parameters: list[Any] = [
            *source_values,
            outside,
            ZERO_HUE_MASK,
            outside,
            ZERO_HUE_MASK,
        ]
        for presence_mask in presence_masks:
            parameters.extend((presence_mask, ZERO_HUE_MASK))
        parameters.append(candidate_limit)
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [Artwork.from_mapping(dict(row)) for row in rows]

    def _fetch_present_section_candidates(
        self,
        sections: tuple[tuple[float, float], ...],
        sources: tuple[str, ...],
        candidate_limit: int = 50_000,
    ) -> list[Artwork]:
        if not self.is_postgres:
            raise RuntimeError("Hue-mask search requires Postgres")

        source_values = sources or ("magic", "met")
        source_clause = " OR ".join("source = %s" for _ in source_values)
        presence_masks = [_selected_mask((section,)) for section in sections]
        presence_clauses = []
        for presence_mask in presence_masks:
            selected_bins = [
                index for index, bit in enumerate(presence_mask) if bit == "1"
            ]
            raw_mass = " + ".join(
                f"COALESCE((hue_histogram ->> {index})::double precision, 0.0)"
                for index in selected_bins
            ) or "0.0"
            presence_clauses.append(
                "AND (hue_mask & %s::bit(72)) <> %s::bit(72) "
                f"AND ({raw_mass}) >= %s"
            )
        query = f"""
            SELECT id, source, source_id, title, artist, year, image_url,
                   thumbnail_url, source_url, license_label, hue_histogram,
                   area_hue_histogram, dominant_hue, colorfulness
            FROM artworks
            WHERE ({source_clause})
              AND hue_mask IS NOT NULL
              {" ".join(presence_clauses)}
            ORDER BY colorfulness DESC
            LIMIT %s
        """
        parameters: list[Any] = [*source_values]
        for presence_mask in presence_masks:
            parameters.extend(
                (
                    presence_mask,
                    ZERO_HUE_MASK,
                    MINIMUM_RAW_SECTION_PRESENCE,
                )
            )
        parameters.append(candidate_limit)
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [Artwork.from_mapping(dict(row)) for row in rows]

    def search(
        self,
        *,
        center: float,
        span: float,
        minimum_coverage: float,
        sources: tuple[str, ...],
        limit: int = 24,
    ) -> list[ArtworkMatch]:
        normalized_center = center % 360.0
        if minimum_coverage >= 1.0 and self.exact_masks_ready and self.is_postgres:
            candidates = self._fetch_exact_candidates(
                ((normalized_center, span),),
                sources,
            )
        else:
            candidates = self._fetch_candidates(normalized_center, span, sources)
        return self._rank_candidates(candidates, center, span, minimum_coverage)[:limit]

    def search_sections(
        self,
        *,
        sections: tuple[tuple[float, float], ...],
        minimum_coverage: float,
        sources: tuple[str, ...],
        limit: int = 24,
    ) -> list[ArtworkMatch]:
        if minimum_coverage >= 1.0 and self.exact_masks_ready and self.is_postgres:
            ranked = self._rank_section_artworks(
                self._fetch_exact_candidates(sections, sources),
                sections,
            )
        else:
            ranked = self._rank_section_candidates(sections, sources)
        return [
            match for match in ranked if match.coverage >= minimum_coverage
        ][:limit]

    def search_sections_strictest(
        self,
        *,
        sections: tuple[tuple[float, float], ...],
        sources: tuple[str, ...],
        minimum_results: int = 5,
        maximum_coverage: float = 1.0,
        limit: int = 24,
    ) -> tuple[float, list[ArtworkMatch]]:
        if maximum_coverage >= 1.0 and self.exact_masks_ready and self.is_postgres:
            exact_ranked = self._rank_section_artworks(
                self._fetch_exact_candidates(sections, sources),
                sections,
            )
            if len(exact_ranked) >= minimum_results:
                return 1.0, exact_ranked[:limit]

        ranked = self._rank_section_candidates(sections, sources)
        at_maximum = [
            match for match in ranked if match.coverage >= maximum_coverage
        ]
        if len(at_maximum) >= minimum_results:
            return maximum_coverage, at_maximum[:limit]

        coverages = sorted(
            (match.coverage for match in ranked),
            reverse=True,
        )
        if len(coverages) >= minimum_results:
            threshold = min(maximum_coverage, coverages[minimum_results - 1])
        elif coverages:
            threshold = min(maximum_coverage, coverages[-1])
        else:
            return maximum_coverage, []

        matches = [match for match in ranked if match.coverage >= threshold]
        return threshold, matches[:limit]

    def _rank_section_candidates(
        self,
        sections: tuple[tuple[float, float], ...],
        sources: tuple[str, ...],
    ) -> list[ArtworkMatch]:
        if self.exact_masks_ready and self.is_postgres:
            return self._rank_section_artworks(
                self._fetch_present_section_candidates(sections, sources),
                sections,
            )

        candidates_by_id: dict[str, Artwork] = {}
        for center, span in sections:
            for artwork in self._fetch_candidates(center, span, sources):
                candidates_by_id[artwork.id] = artwork

        return self._rank_section_artworks(candidates_by_id.values(), sections)

    def _rank_section_artworks(
        self,
        artworks: Iterable[Artwork],
        sections: tuple[tuple[float, float], ...],
    ) -> list[ArtworkMatch]:

        scored: list[ArtworkMatch] = []
        for artwork in artworks:
            coverage = min(
                salient_slices_coverage(artwork.hue_histogram, sections),
                salient_slices_coverage(artwork.area_hue_histogram, sections),
            )
            if any(
                slice_presence(artwork.hue_histogram, center, span)
                < MINIMUM_SECTION_PRESENCE
                for center, span in sections
            ):
                continue

            breadth = slices_breadth(artwork.hue_histogram, sections)
            score = (
                0.65 * breadth
                + 0.30 * coverage
                + 0.05 * artwork.colorfulness
            )
            scored.append(
                ArtworkMatch(
                    artwork=artwork,
                    coverage=coverage,
                    breadth=breadth,
                    score=score,
                )
            )

        scored.sort(
            key=lambda item: (
                item.breadth,
                item.coverage,
                item.artwork.colorfulness,
            ),
            reverse=True,
        )
        return scored

    def _rank_candidates(
        self,
        candidates: list[Artwork],
        center: float,
        span: float,
        minimum_coverage: float,
    ) -> list[ArtworkMatch]:
        scored: list[ArtworkMatch] = []
        for artwork in candidates:
            coverage = min(
                salient_slice_coverage(artwork.hue_histogram, center, span),
                salient_slice_coverage(artwork.area_hue_histogram, center, span),
            )
            if coverage < minimum_coverage:
                continue
            score = rank_score(
                artwork.hue_histogram,
                artwork.area_hue_histogram,
                center,
                span,
                artwork.colorfulness,
            )
            breadth = slice_breadth(artwork.hue_histogram, center, span)
            scored.append(
                ArtworkMatch(
                    artwork=artwork,
                    coverage=coverage,
                    breadth=breadth,
                    score=score,
                )
            )
        scored.sort(
            key=lambda item: (
                item.breadth,
                item.coverage,
                item.artwork.colorfulness,
            ),
            reverse=True,
        )
        return scored

    def search_strictest(
        self,
        *,
        center: float,
        span: float,
        sources: tuple[str, ...],
        minimum_results: int = 3,
        limit: int = 30,
    ) -> tuple[float, list[ArtworkMatch]]:
        candidates = self._fetch_candidates(center % 360.0, span, sources)
        ranked = self._rank_candidates(candidates, center, span, 0.0)
        for percentage in range(95, 49, -5):
            threshold = percentage / 100.0
            matches = [match for match in ranked if match.coverage >= threshold]
            if len(matches) >= minimum_results or percentage == 50:
                return threshold, matches[:limit]
        return 0.5, []

    def count(self, sources: tuple[str, ...] = ()) -> int:
        with self._connection() as connection:
            if not sources:
                row = connection.execute("SELECT COUNT(*) AS count FROM artworks").fetchone()
            else:
                placeholder = "%s" if self.is_postgres else "?"
                joined = ", ".join(placeholder for _ in sources)
                row = connection.execute(
                    f"SELECT COUNT(*) AS count FROM artworks WHERE source IN ({joined})",
                    sources,
                ).fetchone()
        if row is None:
            return 0
        return int(dict(row)["count"])

    def source_counts(self) -> dict[str, int]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT source, COUNT(*) AS count FROM artworks GROUP BY source"
            ).fetchall()
        return {str(dict(row)["source"]): int(dict(row)["count"]) for row in rows}

    def source_titles(self, source: str) -> set[str]:
        placeholder = "%s" if self.is_postgres else "?"
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT title FROM artworks WHERE source = {placeholder}",
                (source,),
            ).fetchall()
        return {str(dict(row)["title"]).strip().casefold() for row in rows}

    def source_year_counts(self, source: str) -> dict[int, int]:
        placeholder = "%s" if self.is_postgres else "?"
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                    SELECT year, COUNT(*) AS count
                    FROM artworks
                    WHERE source = {placeholder} AND year IS NOT NULL
                    GROUP BY year
                """,
                (source,),
            ).fetchall()
        return {
            int(dict(row)["year"]): int(dict(row)["count"])
            for row in rows
        }
