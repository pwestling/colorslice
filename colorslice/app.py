from functools import lru_cache
import math
import os
from pathlib import Path
import secrets

from fasthtml.common import (
    A,
    Button,
    Canvas,
    Div,
    Footer,
    Form,
    H2,
    Img,
    Input,
    Label,
    Link,
    Main,
    Meta,
    P,
    Script,
    Small,
    Span,
    Strong,
    fast_app,
)
from starlette.requests import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from colorslice.color import hue_name
from colorslice.models import HUE_BIN_COUNT, ArtworkMatch, ArtworkRecord
from colorslice.repository import (
    CATALOG_PROFILE_VERSION,
    ArtworkRepository,
    sqlite_artwork_count,
)


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
SEED_DATABASE = Path(__file__).resolve().parent.parent / "data/seed.db"
RESULT_LIMIT = 10_000
INITIAL_RESULT_LIMIT = 24
RESULT_PAGE_SIZE = 96
WHEEL_SEGMENT_DEGREES = 15.0
CUSTOM_MINIMUM_RESULTS = 5
repository = ArtworkRepository()
repository.initialize()
if repository.is_postgres:
    needs_catalog_seed = repository.count() < sqlite_artwork_count(SEED_DATABASE)
    needs_profile_upgrade = (
        repository.catalog_profile_version() < CATALOG_PROFILE_VERSION
    )
    if needs_catalog_seed or needs_profile_upgrade:
        repository.seed_from_sqlite(SEED_DATABASE)
        repository.set_catalog_profile_version(CATALOG_PROFILE_VERSION)

app, rt = fast_app(
    title="Colorslice — Art by palette",
    hdrs=(
        Meta(
            name="description",
            content="Browse human-made art by hue.",
        ),
        Meta(name="theme-color", content="#f4f0e8"),
        Link(rel="preconnect", href="https://fonts.googleapis.com"),
        Link(rel="preconnect", href="https://fonts.gstatic.com", crossorigin="anonymous"),
        Link(
            href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=Instrument+Serif:ital@0;1&display=swap",
            rel="stylesheet",
        ),
        Link(rel="stylesheet", href="/static/styles.css"),
        Link(rel="icon", href="/static/favicon.svg", type="image/svg+xml"),
        Script(src="/static/app.js", defer=True),
    )
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


async def cache_public_artwork_responses(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in {"/artworks", "/artworks/page"} and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=60"
        response.headers["Vercel-CDN-Cache-Control"] = (
            "public, max-age=86400, stale-while-revalidate=604800"
        )
    return response


app.add_middleware(BaseHTTPMiddleware, dispatch=cache_public_artwork_responses)


def _source_label(source: str) -> str:
    return "Magic: The Gathering" if source == "magic" else "The Met"


def _artwork_card(match: ArtworkMatch):
    artwork = match.artwork
    if artwork.year is None:
        year = ""
    elif artwork.year < 0:
        year = f" · {abs(artwork.year)} BCE"
    else:
        year = f" · {artwork.year}"
    artist = artwork.artist or "Unknown artist"
    return A(
        Div(
            Img(
                src=artwork.thumbnail_url,
                alt=f"{artwork.title} by {artist}",
                loading="lazy",
                decoding="async",
            ),
            Div(
                Span(_source_label(artwork.source), cls=f"source-badge source-{artwork.source}"),
                Span(f"{round(match.coverage * 100)}% in slice", cls="match-badge"),
                cls="card-badges",
            ),
            Div(
                style=f"--dominant-hue: {artwork.dominant_hue:.1f}deg",
                cls="dominant-dot",
                title=f"Dominant hue {artwork.dominant_hue:.0f}°",
            ),
            cls="art-image-wrap",
        ),
        Div(
            H2(artwork.title),
            P(f"{artist}{year}", cls="artist-line"),
            Small(artwork.license_label),
            cls="art-card-copy",
        ),
        href=artwork.source_url,
        target="_blank",
        rel="noreferrer",
        cls="art-card",
        aria_label=f"View {artwork.title} by {artist} at its source",
    )


def _empty_state(center: float, span: float, strictness: float, total: int):
    if total == 0:
        return Div(
            P("The gallery is waiting for its first artworks.", cls="empty-title"),
            P(
                "Run the ingestion command locally or connect the production database to populate it.",
                cls="empty-copy",
            ),
            cls="empty-state",
        )
    return Div(
        P("No matches in this slice.", cls="empty-title"),
        cls="empty-state",
    )


@lru_cache(maxsize=192)
def _cached_matches(
    center: float,
    matching_span: float,
    strictness: float,
    sources: tuple[str, ...],
    auto_min_results: int = 0,
) -> tuple[float, tuple[ArtworkMatch, ...]]:
    if auto_min_results:
        strictness, matches = repository.search_strictest(
            center=center,
            span=matching_span,
            sources=sources,
            minimum_results=auto_min_results,
            limit=RESULT_LIMIT,
        )
    else:
        matches = repository.search(
            center=center,
            span=matching_span,
            minimum_coverage=strictness,
            sources=sources,
            limit=RESULT_LIMIT,
        )
    return strictness, tuple(matches)


@lru_cache(maxsize=192)
def _cached_section_matches(
    sections: tuple[tuple[float, float], ...],
    strictness: float,
    sources: tuple[str, ...],
) -> tuple[float, tuple[ArtworkMatch, ...]]:
    if len(sections) > 1:
        strictness, matches = repository.search_sections_strictest(
            sections=sections,
            sources=sources,
            minimum_results=CUSTOM_MINIMUM_RESULTS,
            maximum_coverage=strictness,
            limit=RESULT_LIMIT,
        )
    else:
        matches = repository.search_sections(
            sections=sections,
            minimum_coverage=strictness,
            sources=sources,
            limit=RESULT_LIMIT,
        )
    return strictness, tuple(matches)


def _parse_custom_sections(value: str) -> tuple[tuple[float, float], ...]:
    sections = []
    for raw_section in value.split(",")[:4]:
        try:
            raw_start, raw_end = raw_section.split(":", maxsplit=1)
            start = float(raw_start) % 360.0
            end = float(raw_end) % 360.0
        except ValueError:
            continue
        if not math.isfinite(start) or not math.isfinite(end):
            continue
        span = (end - start) % 360.0
        if span < 1.0 or span > 359.0:
            continue
        center = (start + span / 2.0) % 360.0
        sections.append((round(center, 3), round(span, 3)))
    return tuple(sections)


def _profile_values(value: object) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != HUE_BIN_COUNT:
        raise ValueError("Invalid hue profile")
    profile = tuple(float(item) for item in value)
    if any(not math.isfinite(item) or item < 0.0 for item in profile):
        raise ValueError("Invalid hue profile")
    return profile


def _import_entry(value: object):
    if not isinstance(value, dict):
        raise ValueError("Invalid import entry")
    raw_record = value.get("record")
    if not isinstance(raw_record, dict):
        raise ValueError("Invalid artwork record")

    source_id = raw_record.get("source_id")
    title = raw_record.get("title")
    artist = raw_record.get("artist")
    image_url = raw_record.get("image_url")
    thumbnail_url = raw_record.get("thumbnail_url")
    source_url = raw_record.get("source_url")
    license_label = raw_record.get("license_label")
    if not all(
        isinstance(item, str) and item
        for item in (
            source_id,
            title,
            artist,
            image_url,
            thumbnail_url,
            source_url,
            license_label,
        )
    ):
        raise ValueError("Invalid artwork record")
    if not source_id.startswith("illustration:"):
        raise ValueError("Invalid illustration identifier")

    raw_year = raw_record.get("year")
    if raw_year is not None and not isinstance(raw_year, int):
        raise ValueError("Invalid artwork year")
    record = ArtworkRecord(
        source="magic",
        source_id=source_id,
        title=title,
        artist=artist,
        year=raw_year,
        image_url=image_url,
        thumbnail_url=thumbnail_url,
        analysis_url=image_url,
        source_url=source_url,
        license_label=license_label,
    )
    dominant_hue = float(value.get("dominant_hue", -1.0))
    colorfulness = float(value.get("colorfulness", -1.0))
    if (
        not math.isfinite(dominant_hue)
        or not 0.0 <= dominant_hue <= 360.0
        or not math.isfinite(colorfulness)
        or not 0.0 <= colorfulness <= 1.0
    ):
        raise ValueError("Invalid artwork profile metadata")
    return (
        record,
        _profile_values(value.get("hue_histogram")),
        _profile_values(value.get("area_hue_histogram")),
        dominant_hue,
        colorfulness,
    )


def _next_offset(offset: int, returned: int, total: int) -> str:
    next_offset = offset + returned
    return str(next_offset) if next_offset < total else ""


def _matching_span(span: float, mode: str) -> float:
    if mode == "custom":
        return span
    return max(0.0, span - WHEEL_SEGMENT_DEGREES)


def _artwork_grid(matches: tuple[ArtworkMatch, ...]):
    visible = matches[:INITIAL_RESULT_LIMIT]
    return Div(
        *(_artwork_card(match) for match in visible),
        cls="art-grid",
        data_next_offset=_next_offset(0, len(visible), len(matches)),
    )


def artwork_results(
    center: float,
    span: float,
    strictness: float,
    sources: tuple[str, ...],
    auto_min_results: int = 0,
    mode: str = "standard",
    sections: tuple[tuple[float, float], ...] = (),
):
    matching_span = _matching_span(span, mode)
    if mode == "custom" and sections:
        strictness, matches = _cached_section_matches(sections, strictness, sources)
        section_count = len(sections)
        matching_span = sum(section_span for _, section_span in sections)
        heading_text = (
            f"{round(matching_span)}° across {section_count} sections"
            if section_count > 1
            else f"{round(matching_span)}° of {hue_name(sections[0][0])}"
        )
    else:
        strictness, matches = _cached_matches(
            center,
            matching_span,
            strictness,
            sources,
            auto_min_results,
        )
        section_count = 1
        heading_text = f"{round(span)}° of {hue_name(center)}"
    heading = Div(
        H2(
            heading_text,
            Span(f" · {len(matches)} matches", cls="result-count"),
            cls="results-title",
        ),
        cls="results-heading",
        data_strictness=f"{strictness:.3f}",
        data_match_span=f"{matching_span:.1f}",
        data_mode=mode,
        data_sections=str(section_count),
    )
    content = (
        _artwork_grid(matches)
        if matches
        else _empty_state(center, span, strictness, repository.count(sources))
    )
    return heading, content


def artwork_page(
    center: float,
    span: float,
    strictness: float,
    sources: tuple[str, ...],
    offset: int,
    mode: str = "standard",
    sections: tuple[tuple[float, float], ...] = (),
):
    matching_span = _matching_span(span, mode)
    if mode == "custom" and sections:
        _, matches = _cached_section_matches(sections, strictness, sources)
    else:
        _, matches = _cached_matches(center, matching_span, strictness, sources, 0)
    page = matches[offset:offset + RESULT_PAGE_SIZE]
    return Div(
        *(_artwork_card(match) for match in page),
        cls="art-page",
        data_next_offset=_next_offset(offset, len(page), len(matches)),
    )


def _control_panel(counts: dict[str, int]):
    magic_count = counts.get("magic", 0)
    met_count = counts.get("met", 0)
    return Form(
        Input(type="hidden", id="center-input", name="center", value="75"),
        Input(type="hidden", id="span-input", name="span", value="120"),
        Input(type="hidden", id="mode-input", name="mode", value="standard"),
        Input(type="hidden", id="ranges-input", name="ranges", value=""),
        Input(type="hidden", name="strictness", value="1"),
        Div(
            Div(
                P("SLICE SIZE", cls="control-label"),
                Div(
                    Button(
                        Span("¼", cls="fraction-mark"),
                        Span("25%"),
                        type="button",
                        data_span="90",
                        cls="slice-option",
                    ),
                    Button(
                        Span("⅓", cls="fraction-mark"),
                        Span("33%"),
                        type="button",
                        data_span="120",
                        cls="slice-option active",
                    ),
                    Button(
                        "Custom",
                        type="button",
                        data_mode="custom",
                        cls="slice-option",
                    ),
                    cls="segmented",
                ),
                Div(
                    P(
                        Strong("120°", id="custom-angle"),
                        Span(" · "),
                        Span("33.3% of wheel", id="custom-percent"),
                        Span(" · "),
                        Span("1 section", id="custom-section-count"),
                        cls="custom-summary",
                    ),
                    Div(
                        Button(
                            "+ Add section",
                            type="button",
                            id="add-custom-section",
                            cls="custom-section-action",
                        ),
                        cls="custom-section-actions",
                    ),
                    id="custom-controls",
                    cls="custom-controls",
                    hidden=True,
                ),
                cls="control-block",
            ),
            Div(
                P("COLLECTIONS", cls="control-label"),
                Div(
                    Label(
                        Input(type="checkbox", name="source", value="magic", checked=True),
                        Span("Magic", cls="source-name"),
                        Span(str(magic_count), cls="source-count"),
                        cls="source-toggle",
                    ),
                    Label(
                        Input(type="checkbox", name="source", value="met", checked=True),
                        Span("The Met", cls="source-name"),
                        Span(str(met_count), cls="source-count"),
                        cls="source-toggle",
                    ),
                    cls="source-list",
                ),
                cls="control-block",
            ),
            cls="controls-inner",
        ),
        id="palette-controls",
        cls="control-panel",
    )


@rt("/")
def get():
    counts = repository.source_counts()
    initial_results = artwork_results(75.0, 120.0, 1.0, ("magic", "met"))
    return (
        Main(
            Div(
                Div(
                    Div(
                        Canvas(
                            id="color-wheel",
                            width="760",
                            height="760",
                            tabindex="0",
                            aria_label="24-segment color wheel",
                        ),
                        Button(
                            Span(
                                "DRAG TO ROTATE",
                                cls="wheel-action-label",
                            ),
                            Strong("75°", id="hue-readout"),
                            Span("orange — yellow", id="hue-range-name"),
                            type="button",
                            id="wheel-center",
                            aria_label="Drag the wheel to choose a hue",
                        ),
                        cls="wheel-shell",
                    ),
                    cls="wheel-column",
                ),
                cls="hero",
            ),
            _control_panel(counts),
            Div(*initial_results, id="art-results", cls="results-section", aria_live="polite"),
            cls="page-main",
        ),
        Footer(
            P(
                "Magic imagery © Wizards of the Coast. Museum rights labels are provided by source.",
                cls="legal-copy",
            ),
            cls="site-footer",
        ),
    )


@rt("/artworks")
def get(
    request: Request,
    center: float = 75.0,
    span: float = 120.0,
    strictness: float = 1.0,
    auto_min_results: int = 0,
    mode: str = "standard",
    ranges: str = "",
):
    sources = tuple(request.query_params.getlist("source"))
    allowed_sources = tuple(source for source in sources if source in {"magic", "met"})
    safe_center = center % 360.0
    safe_mode = "custom" if mode == "custom" else "standard"
    safe_span = (
        min(359.0, max(1.0, span))
        if safe_mode == "custom"
        else min(180.0, max(30.0, span))
    )
    safe_strictness = min(1.0, max(0.0, strictness))
    safe_auto_minimum = min(30, max(0, auto_min_results))
    safe_sections = _parse_custom_sections(ranges) if safe_mode == "custom" else ()
    return artwork_results(
        safe_center,
        safe_span,
        safe_strictness,
        allowed_sources,
        safe_auto_minimum,
        safe_mode,
        safe_sections,
    )


@rt("/artworks/page")
def get(
    request: Request,
    center: float = 75.0,
    span: float = 120.0,
    strictness: float = 1.0,
    offset: int = INITIAL_RESULT_LIMIT,
    mode: str = "standard",
    ranges: str = "",
):
    sources = tuple(request.query_params.getlist("source"))
    allowed_sources = tuple(source for source in sources if source in {"magic", "met"})
    safe_center = center % 360.0
    safe_mode = "custom" if mode == "custom" else "standard"
    safe_span = (
        min(359.0, max(1.0, span))
        if safe_mode == "custom"
        else min(180.0, max(30.0, span))
    )
    safe_strictness = min(1.0, max(0.0, strictness))
    safe_offset = max(INITIAL_RESULT_LIMIT, offset)
    safe_sections = _parse_custom_sections(ranges) if safe_mode == "custom" else ()
    return artwork_page(
        safe_center,
        safe_span,
        safe_strictness,
        allowed_sources,
        safe_offset,
        safe_mode,
        safe_sections,
    )


@rt("/healthz")
def get():
    return JSONResponse(
        {
            "status": "ok",
            "artworks": repository.count(),
            "database": "postgres" if repository.is_postgres else "sqlite",
        }
    )


@rt("/internal/artworks/import")
async def post(request: Request):
    expected_token = os.environ.get("COLORSLICE_IMPORT_TOKEN")
    supplied_token = request.headers.get("x-colorslice-import-token", "")
    if (
        not expected_token
        or not supplied_token
        or not secrets.compare_digest(expected_token, supplied_token)
    ):
        return JSONResponse({"error": "Not found"}, status_code=404)

    try:
        payload = await request.json()
        raw_entries = payload.get("entries") if isinstance(payload, dict) else None
        if not isinstance(raw_entries, list) or not 1 <= len(raw_entries) <= 100:
            raise ValueError("Import batches must contain 1–100 entries")
        entries = [_import_entry(value) for value in raw_entries]
    except (TypeError, ValueError):
        return JSONResponse({"error": "Invalid import batch"}, status_code=400)

    records = [entry[0] for entry in entries]
    existing = repository.existing_record_source_ids(records)
    new_entries = [entry for entry in entries if entry[0].source_id not in existing]
    repository.upsert_many(new_entries)
    return JSONResponse(
        {
            "stored": [entry[0].source_id for entry in new_entries],
            "existing": sorted(existing),
            "catalog_size": repository.count(("magic",)),
        }
    )
