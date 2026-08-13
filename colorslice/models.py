from dataclasses import dataclass
from datetime import date
import json
from typing import Self


HUE_BIN_COUNT = 72


@dataclass(frozen=True, slots=True)
class Artwork:
    id: str
    source: str
    source_id: str
    title: str
    artist: str
    year: int | None
    image_url: str
    thumbnail_url: str
    source_url: str
    license_label: str
    hue_histogram: tuple[float, ...]
    area_hue_histogram: tuple[float, ...]
    dominant_hue: float
    colorfulness: float

    @classmethod
    def from_mapping(cls, row: dict[str, object]) -> Self:
        raw_histogram = row["hue_histogram"]
        if isinstance(raw_histogram, str):
            parsed_histogram = json.loads(raw_histogram)
        else:
            parsed_histogram = raw_histogram
        if not isinstance(parsed_histogram, (list, tuple)):
            raise ValueError("hue_histogram must be a list or tuple")

        raw_area_histogram = row["area_hue_histogram"]
        if isinstance(raw_area_histogram, str):
            parsed_area_histogram = json.loads(raw_area_histogram)
        else:
            parsed_area_histogram = raw_area_histogram
        if not isinstance(parsed_area_histogram, (list, tuple)):
            raise ValueError("area_hue_histogram must be a list or tuple")

        raw_year = row["year"]
        return cls(
            id=str(row["id"]),
            source=str(row["source"]),
            source_id=str(row["source_id"]),
            title=str(row["title"]),
            artist=str(row["artist"]),
            year=int(raw_year) if raw_year is not None else None,
            image_url=str(row["image_url"]),
            thumbnail_url=str(row["thumbnail_url"]),
            source_url=str(row["source_url"]),
            license_label=str(row["license_label"]),
            hue_histogram=tuple(float(value) for value in parsed_histogram),
            area_hue_histogram=tuple(
                float(value) for value in parsed_area_histogram
            ),
            dominant_hue=float(row["dominant_hue"]),
            colorfulness=float(row["colorfulness"]),
        )


@dataclass(frozen=True, slots=True)
class ArtworkRecord:
    source: str
    source_id: str
    title: str
    artist: str
    year: int | None
    image_url: str
    thumbnail_url: str
    analysis_url: str
    source_url: str
    license_label: str

    @property
    def id(self) -> str:
        return f"{self.source}:{self.source_id}"


@dataclass(frozen=True, slots=True)
class ArtworkMatch:
    artwork: Artwork
    coverage: float
    breadth: float
    score: float


def year_from_iso_date(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value).year
    except ValueError:
        return None
