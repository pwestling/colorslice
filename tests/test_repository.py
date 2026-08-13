from colorslice.models import ArtworkRecord
from colorslice.repository import ArtworkRepository


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
