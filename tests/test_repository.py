import pytest

from colorslice.models import ArtworkRecord
from colorslice.repository import ArtworkRepository, _histogram_mask, _selected_mask


def histogram_at(*bins):
    values = [0.0] * 72
    weight = 1.0 / len(bins)
    for index in bins:
        values[index] = weight
    return tuple(values)


def histogram_with_coverage(inside_weight):
    values = [0.0] * 72
    values[6] = inside_weight
    values[40] = 1.0 - inside_weight
    return tuple(values)


def record(source_id, title):
    return ArtworkRecord(
        source="met",
        source_id=source_id,
        title=title,
        artist="A painter",
        year=1900,
        image_url="https://example.com/image.jpg",
        thumbnail_url="https://example.com/thumb.jpg",
        analysis_url="https://example.com/thumb.jpg",
        source_url="https://example.com/work",
        license_label="Public Domain",
    )


def test_repository_ranks_and_filters_by_slice(tmp_path, monkeypatch):
    database_path = tmp_path / "test.db"
    monkeypatch.setenv("COLORSLICE_DB_PATH", str(database_path))
    repository = ArtworkRepository()
    repository.initialize()
    warm_histogram = histogram_at(5, 6, 7)
    cool_histogram = histogram_at(40, 41, 42)
    repository.upsert(record("warm", "Warm work"), warm_histogram, warm_histogram, 32.5, 0.8)
    repository.upsert(record("cool", "Cool work"), cool_histogram, cool_histogram, 207.5, 0.9)

    matches = repository.search(
        center=30.0,
        span=90.0,
        minimum_coverage=0.7,
        sources=("met",),
    )

    assert [match.artwork.title for match in matches] == ["Warm work"]
    assert matches[0].coverage == 1.0


def test_repository_ranks_broad_palettes_above_monochrome_matches(tmp_path, monkeypatch):
    database_path = tmp_path / "breadth.db"
    monkeypatch.setenv("COLORSLICE_DB_PATH", str(database_path))
    repository = ArtworkRepository()
    repository.initialize()
    monochrome = histogram_at(18)
    broad = histogram_at(10, 18, 26)
    repository.upsert(record("mono", "Monochrome"), monochrome, monochrome, 92.5, 0.9)
    repository.upsert(record("broad", "Broad palette"), broad, broad, 92.5, 0.7)

    matches = repository.search(
        center=90.0,
        span=90.0,
        minimum_coverage=0.95,
        sources=("met",),
    )

    assert [match.artwork.title for match in matches] == ["Broad palette", "Monochrome"]


def test_repository_selects_strictest_threshold_with_three_matches(tmp_path, monkeypatch):
    database_path = tmp_path / "strictest.db"
    monkeypatch.setenv("COLORSLICE_DB_PATH", str(database_path))
    repository = ArtworkRepository()
    repository.initialize()
    for source_id, coverage in (("exact", 1.0), ("close", 0.81), ("third", 0.76), ("loose", 0.49)):
        repository.upsert(
            record(source_id, source_id.title()),
            histogram_with_coverage(coverage),
            histogram_with_coverage(coverage),
            32.5,
            0.8,
        )

    threshold, matches = repository.search_strictest(
        center=30.0,
        span=90.0,
        sources=("met",),
        minimum_results=3,
    )

    assert threshold == 0.75
    assert [match.artwork.title for match in matches] == ["Exact", "Close", "Third"]


def test_repository_filters_by_area_but_ranks_by_chroma_breadth(tmp_path, monkeypatch):
    database_path = tmp_path / "area-coverage.db"
    monkeypatch.setenv("COLORSLICE_DB_PATH", str(database_path))
    repository = ArtworkRepository()
    repository.initialize()
    broad_chroma_histogram = histogram_at(0, 7, 14)
    visible_outside_accent = histogram_with_coverage(0.91)
    repository.upsert(
        record("accent", "Visible blue accent"),
        broad_chroma_histogram,
        visible_outside_accent,
        52.5,
        0.8,
    )

    exact_matches = repository.search(
        center=30.0,
        span=90.0,
        minimum_coverage=0.95,
        sources=("met",),
    )
    loose_matches = repository.search(
        center=30.0,
        span=90.0,
        minimum_coverage=0.90,
        sources=("met",),
    )

    assert exact_matches == []
    assert [match.artwork.title for match in loose_matches] == ["Visible blue accent"]
    assert loose_matches[0].coverage == 0.91
    assert loose_matches[0].breadth > 0.6


def test_repository_rejects_a_small_but_vivid_outside_accent(tmp_path, monkeypatch):
    database_path = tmp_path / "vivid-accent.db"
    monkeypatch.setenv("COLORSLICE_DB_PATH", str(database_path))
    repository = ArtworkRepository()
    repository.initialize()
    vivid_accent_histogram = histogram_with_coverage(0.89)
    small_accent_area = histogram_with_coverage(0.97)
    repository.upsert(
        record("vivid", "Small vivid accent"),
        vivid_accent_histogram,
        small_accent_area,
        32.5,
        0.8,
    )

    matches = repository.search(
        center=30.0,
        span=90.0,
        minimum_coverage=0.95,
        sources=("met",),
    )

    assert matches == []


def test_repository_requires_color_in_every_custom_section(tmp_path, monkeypatch):
    database_path = tmp_path / "multiple-sections.db"
    monkeypatch.setenv("COLORSLICE_DB_PATH", str(database_path))
    repository = ArtworkRepository()
    repository.initialize()
    two_color = histogram_at(6, 42)
    warm_only = histogram_at(6)
    repository.upsert(record("two", "Two colors"), two_color, two_color, 32.5, 0.9)
    repository.upsert(record("warm", "Warm only"), warm_only, warm_only, 32.5, 0.9)

    matches = repository.search_sections(
        sections=((32.5, 15.0), (212.5, 15.0)),
        minimum_coverage=1.0,
        sources=("met",),
    )

    assert [match.artwork.title for match in matches] == ["Two colors"]


def test_repository_accepts_a_meaningful_accent_in_second_section(tmp_path, monkeypatch):
    database_path = tmp_path / "section-accent.db"
    monkeypatch.setenv("COLORSLICE_DB_PATH", str(database_path))
    repository = ArtworkRepository()
    repository.initialize()
    accent = [0.0] * 72
    accent[6] = 0.98
    accent[42] = 0.02
    too_small = [0.0] * 72
    too_small[6] = 0.99
    too_small[42] = 0.01
    repository.upsert(
        record("accent", "Visible accent"),
        tuple(accent),
        tuple(accent),
        32.5,
        0.9,
    )
    repository.upsert(
        record("trace", "Color trace"),
        tuple(too_small),
        tuple(too_small),
        32.5,
        0.9,
    )

    matches = repository.search_sections(
        sections=((32.5, 15.0), (212.5, 15.0)),
        minimum_coverage=1.0,
        sources=("met",),
    )

    assert [match.artwork.title for match in matches] == ["Visible accent"]


def test_repository_selects_fifth_best_custom_section_coverage(tmp_path, monkeypatch):
    database_path = tmp_path / "strictest-sections.db"
    monkeypatch.setenv("COLORSLICE_DB_PATH", str(database_path))
    repository = ArtworkRepository()
    repository.initialize()

    for index, coverage in enumerate((1.0, 0.999, 0.995, 0.99, 0.98, 0.90)):
        histogram = [0.0] * 72
        histogram[6] = coverage - 0.03
        histogram[42] = 0.03
        histogram[25] = 1.0 - coverage
        repository.upsert(
            record(str(index), f"Coverage {coverage}"),
            tuple(histogram),
            tuple(histogram),
            32.5,
            0.9,
        )

    threshold, matches = repository.search_sections_strictest(
        sections=((32.5, 15.0), (212.5, 15.0)),
        sources=("met",),
        minimum_results=5,
    )

    assert threshold == pytest.approx(0.98)
    assert len(matches) == 5
    assert all(match.coverage >= threshold for match in matches)


def test_hue_masks_follow_noise_filtering_and_selected_sections():
    noisy = [0.0] * 72
    noisy[6] = 0.9995
    noisy[40] = 0.0005

    assert _histogram_mask(tuple(noisy))[6] == "1"
    assert _histogram_mask(tuple(noisy))[40] == "0"
    selected = _selected_mask(((32.5, 15.0), (212.5, 15.0)))
    assert selected[6] == "1"
    assert selected[42] == "1"
    assert selected[24] == "0"


def test_repository_backfills_missing_hue_masks(tmp_path, monkeypatch):
    database_path = tmp_path / "mask-backfill.db"
    monkeypatch.setenv("COLORSLICE_DB_PATH", str(database_path))
    repository = ArtworkRepository()
    repository.initialize()
    histogram = histogram_at(6, 7)
    repository.upsert(record("masked", "Masked work"), histogram, histogram, 32.5, 0.8)
    with repository._connection() as connection:
        connection.execute(
            "UPDATE artworks SET hue_mask = NULL, area_hue_mask = NULL"
        )
        connection.commit()

    processed, remaining = repository.backfill_missing_masks()

    assert (processed, remaining) == (1, 0)
    assert repository.exact_masks_ready


def test_repository_deletes_an_artwork_source(tmp_path, monkeypatch):
    database_path = tmp_path / "delete-source.db"
    monkeypatch.setenv("COLORSLICE_DB_PATH", str(database_path))
    repository = ArtworkRepository()
    repository.initialize()
    histogram = histogram_at(6)
    repository.upsert(record("museum", "Museum work"), histogram, histogram, 32.5, 0.8)

    removed = repository.delete_source("met")

    assert removed == 1
    assert repository.count() == 0
