import pytest
from starlette.testclient import TestClient

from colorslice.app import (
    CUSTOM_MINIMUM_RESULTS,
    INITIAL_RESULT_LIMIT,
    RELAXED_RESULT_BATCH_SIZE,
    RESULT_LIMIT,
    WHEEL_SEGMENT_DEGREES,
    _cached_matches,
    _cached_relaxed_page,
    _cached_section_matches,
    app,
    repository,
)


client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_match_cache():
    _cached_matches.cache_clear()
    _cached_relaxed_page.cache_clear()
    _cached_section_matches.cache_clear()
    yield
    _cached_matches.cache_clear()
    _cached_relaxed_page.cache_clear()
    _cached_section_matches.cache_clear()


def test_home_page_contains_palette_controls():
    response = client.get("/")
    assert response.status_code == 200
    assert "DRAG SLICE TO MOVE" in response.text
    assert 'id="color-wheel"' in response.text
    assert "Continuous color wheel" in response.text
    assert "24-segment color wheel" not in response.text
    assert 'class="wheel-label' not in response.text
    assert "Magic" in response.text
    assert "The Met" not in response.text
    assert "COLLECTIONS" not in response.text
    assert 'name="source"' not in response.text
    assert "Find Magic: The Gathering artwork that matches your selected colors." in response.text
    assert "human-made" not in response.text
    assert "PALETTE FIT" not in response.text
    assert 'name="strictness" value="1"' in response.text
    assert 'data-strictness="1.000"' in response.text
    assert 'data-match-span="105.0"' in response.text
    assert "Custom" in response.text
    assert 'name="mode" value="standard"' in response.text
    assert 'name="ranges" value=""' in response.text
    assert 'id="custom-controls"' in response.text
    assert 'id="custom-loading-status"' in response.text
    assert 'id="custom-loading-message"' in response.text
    assert 'role="status"' in response.text
    assert 'hidden id="custom-loading-status"' in response.text
    assert "+ Add section" in response.text
    assert "Show more images" in response.text
    assert 'data-relaxed-cutoff="1.0"' in response.text
    assert 'data-custom-edge=' not in response.text
    assert 'id="custom-section-list"' not in response.text
    assert 'id="remove-custom-section"' not in response.text
    assert 'class="wordmark"' not in response.text


def test_artwork_endpoint_supports_high_match_thresholds():
    for strictness in ("0.99", "0.995", "0.998"):
        response = client.get(
            f"/artworks?center=75&span=120&strictness={strictness}"
        )

        assert response.status_code == 200
        assert f'data-strictness="{float(strictness):.3f}"' in response.text


def test_artwork_responses_are_shared_at_the_edge():
    response = client.get(
        "/artworks?center=75&span=120&strictness=1"
    )
    page = client.get(
        f"/artworks/page?center=75&span=120&strictness=1&offset={INITIAL_RESULT_LIMIT}"
    )

    assert response.headers["cache-control"] == "public, max-age=60"
    assert "max-age=86400" in response.headers["vercel-cdn-cache-control"]
    assert page.headers["cache-control"] == "public, max-age=60"


def test_relaxed_endpoint_pages_below_the_current_cutoff(monkeypatch):
    standard_requests = []
    section_requests = []

    def search_relaxed(**parameters):
        standard_requests.append(parameters)
        return []

    def search_sections_relaxed(**parameters):
        section_requests.append(parameters)
        return []

    monkeypatch.setattr(repository, "search_relaxed", search_relaxed)
    monkeypatch.setattr(
        repository,
        "search_sections_relaxed",
        search_sections_relaxed,
    )

    standard = client.get(
        "/artworks/more?center=76&span=120&maximum_coverage=0.99&offset=10"
    )
    custom = client.get(
        "/artworks/more?mode=custom&ranges=15:45,195:225"
        "&maximum_coverage=0.98&offset=20"
    )

    assert standard.status_code == 200
    assert custom.status_code == 200
    assert 'data-returned="0"' in standard.text
    assert standard_requests == [
        {
            "center": 76.0,
            "span": 120.0 - WHEEL_SEGMENT_DEGREES,
            "maximum_coverage": 0.99,
            "sources": ("magic",),
            "offset": 10,
            "limit": RELAXED_RESULT_BATCH_SIZE + 1,
        }
    ]
    assert section_requests == [
        {
            "sections": ((30.0, 30.0), (210.0, 30.0)),
            "maximum_coverage": 0.98,
            "sources": ("magic",),
            "offset": 20,
            "limit": RELAXED_RESULT_BATCH_SIZE + 1,
        }
    ]


def test_first_page_and_background_page_share_ranked_match_cache(monkeypatch):
    search_calls = 0

    def search(**parameters):
        nonlocal search_calls
        search_calls += 1
        return []

    monkeypatch.setattr(repository, "search", search)
    client.get("/artworks?center=90&span=120&strictness=1")
    client.get(
        f"/artworks/page?center=90&span=120&strictness=1&offset={INITIAL_RESULT_LIMIT}"
    )

    assert search_calls == 1


def test_artwork_endpoint_requests_every_match(monkeypatch):
    requested_limits = []
    requested_spans = []
    requested_sources = []

    def search(**parameters):
        requested_limits.append(parameters["limit"])
        requested_spans.append(parameters["span"])
        requested_sources.append(parameters["sources"])
        return []

    monkeypatch.setattr(repository, "search", search)
    response = client.get(
        "/artworks?center=75&span=120&strictness=0.99"
    )
    second_response = client.get(
        "/artworks?center=75&span=90&strictness=0.99"
    )
    custom_response = client.get(
        "/artworks?center=91.5&span=37&mode=custom&strictness=0.99&source=met"
    )

    assert response.status_code == 200
    assert second_response.status_code == 200
    assert custom_response.status_code == 200
    assert requested_limits == [RESULT_LIMIT, RESULT_LIMIT, RESULT_LIMIT]
    assert requested_spans == [
        120.0 - WHEEL_SEGMENT_DEGREES,
        90.0 - WHEEL_SEGMENT_DEGREES,
        37.0,
    ]
    assert requested_sources == [("magic",), ("magic",), ("magic",)]


def test_custom_mode_supports_precise_narrow_and_wide_spans(monkeypatch):
    requested_spans = []

    def search(**parameters):
        requested_spans.append(parameters["span"])
        return []

    monkeypatch.setattr(repository, "search", search)
    narrow = client.get(
        "/artworks?center=45.5&span=1&mode=custom&strictness=1"
    )
    wide = client.get(
        "/artworks?center=179.5&span=359&mode=custom&strictness=1"
    )

    assert narrow.status_code == 200
    assert wide.status_code == 200
    assert 'data-match-span="1.0"' in narrow.text
    assert 'data-match-span="359.0"' in wide.text
    assert requested_spans == [1.0, 359.0]


def test_custom_mode_searches_multiple_sections_as_one_union(monkeypatch):
    requests = []

    def search_sections_strictest(**parameters):
        requests.append(parameters)
        return 0.993, []

    monkeypatch.setattr(
        repository,
        "search_sections_strictest",
        search_sections_strictest,
    )
    response = client.get(
        "/artworks?center=75&span=120&mode=custom"
        "&ranges=15:45,195:225&strictness=1"
    )

    assert response.status_code == 200
    assert requests[0]["sections"] == ((30.0, 30.0), (210.0, 30.0))
    assert requests[0]["minimum_results"] == CUSTOM_MINIMUM_RESULTS
    assert requests[0]["maximum_coverage"] == 1.0
    assert "60° across 2 sections" in response.text
    assert 'data-strictness="0.993"' in response.text
    assert 'data-match-span="60.0"' in response.text
    assert 'data-sections="2"' in response.text


def test_relaxed_cutoff_preserves_the_adaptive_threshold_precision(monkeypatch):
    threshold = 0.892753458188547

    def search_sections_strictest(**parameters):
        return threshold, []

    monkeypatch.setattr(
        repository,
        "search_sections_strictest",
        search_sections_strictest,
    )
    response = client.get(
        "/artworks?mode=custom&ranges=20:50,200:230&strictness=1"
    )

    assert response.status_code == 200
    assert f'data-relaxed-cutoff="{threshold!r}"' in response.text


def test_health_endpoint_reports_catalog_size():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "sqlite"
