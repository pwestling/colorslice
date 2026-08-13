from functools import lru_cache
from pathlib import Path

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
from colorslice.models import ArtworkMatch
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
):
    matching_span = _matching_span(span, mode)
    strictness, matches = _cached_matches(
        center,
        matching_span,
        strictness,
        sources,
        auto_min_results,
    )
    heading = Div(
        H2(
            f"{round(span)}° of {hue_name(center)}",
            Span(f" · {len(matches)} matches", cls="result-count"),
            cls="results-title",
        ),
        cls="results-heading",
        data_strictness=f"{strictness:.3f}",
        data_match_span=f"{matching_span:.1f}",
        data_mode=mode,
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
):
    matching_span = _matching_span(span, mode)
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
                        cls="custom-summary",
                    ),
                    Div(
                        Div(
                            Span("START", cls="custom-edge-label"),
                            Button(
                                "−",
                                type="button",
                                data_custom_edge="start",
                                data_custom_delta="-1",
                                aria_label="Move start edge counterclockwise by 1 degree",
                            ),
                            Span("15°", id="custom-start"),
                            Button(
                                "+",
                                type="button",
                                data_custom_edge="start",
                                data_custom_delta="1",
                                aria_label="Move start edge clockwise by 1 degree",
                            ),
                            cls="custom-edge-control",
                        ),
                        Div(
                            Span("END", cls="custom-edge-label"),
                            Button(
                                "−",
                                type="button",
                                data_custom_edge="end",
                                data_custom_delta="-1",
                                aria_label="Move end edge counterclockwise by 1 degree",
                            ),
                            Span("135°", id="custom-end"),
                            Button(
                                "+",
                                type="button",
                                data_custom_edge="end",
                                data_custom_delta="1",
                                aria_label="Move end edge clockwise by 1 degree",
                            ),
                            cls="custom-edge-control",
                        ),
                        cls="custom-edge-controls",
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
    return artwork_results(
        safe_center,
        safe_span,
        safe_strictness,
        allowed_sources,
        safe_auto_minimum,
        safe_mode,
    )


@rt("/artworks/page")
def get(
    request: Request,
    center: float = 75.0,
    span: float = 120.0,
    strictness: float = 1.0,
    offset: int = INITIAL_RESULT_LIMIT,
    mode: str = "standard",
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
    return artwork_page(
        safe_center,
        safe_span,
        safe_strictness,
        allowed_sources,
        safe_offset,
        safe_mode,
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
