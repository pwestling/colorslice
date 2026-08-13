from argparse import ArgumentParser
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
import gzip
import json
import math
import os
from pathlib import Path

import httpx

from colorslice.color import (
    ColorProfile,
    analyze_image_bytes,
    noise_filtered_histogram,
    slice_coverage,
)
from colorslice.models import Artwork, ArtworkRecord
from colorslice.repository import ArtworkRepository
from colorslice.sources import ScryfallSource, build_http_client


WHEEL_CENTERS = tuple(range(0, 360, 15))
MATCHING_SPANS = (75, 105)
MAX_ADDITIONS = 5_000
COLOR_TARGET_CENTERS = {
    "W": frozenset((30, 45, 60, 75, 90, 105, 120)),
    "U": frozenset((150, 165, 180, 195, 210, 225, 240, 255, 270)),
    "B": frozenset((225, 240, 255, 270, 285, 300, 315, 330, 345)),
    "R": frozenset((315, 330, 345, 0, 15, 30, 45, 60, 75)),
    "G": frozenset((75, 90, 105, 120, 135, 150, 165, 180)),
    "C": frozenset(WHEEL_CENTERS),
}
TARGET_ART_TAG_LABELS = frozenset(
    (
        "blue background",
        "blue glow",
        "blue magic",
        "pink background",
        "pink glow",
        "pink magic",
        "pink sky",
        "purple background",
        "purple glow",
        "purple magic",
        "turquoise background",
        "turquoise glow",
    )
)


@dataclass(frozen=True, slots=True)
class Candidate:
    record: ArtworkRecord
    color: str
    year: int
    tagged: bool


def parse_args():
    parser = ArgumentParser(
        description=(
            "Add only unique Magic illustrations that improve underfilled fixed slices."
        )
    )
    parser.add_argument("--bulk-file", type=Path, required=True)
    parser.add_argument("--art-tags-file", type=Path)
    parser.add_argument("--tagged-only", action="store_true")
    parser.add_argument("--target-minimum", type=int, default=20)
    parser.add_argument("--max-additions", type=int, default=MAX_ADDITIONS)
    parser.add_argument("--scan-limit", type=int, default=5_000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    return parser.parse_args()


def _profile_histograms(
    hue_histogram: tuple[float, ...],
    area_hue_histogram: tuple[float, ...],
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    return (
        noise_filtered_histogram(hue_histogram),
        noise_filtered_histogram(area_hue_histogram),
    )


def matching_slices(
    hue_histogram: tuple[float, ...],
    area_hue_histogram: tuple[float, ...],
) -> set[tuple[int, int]]:
    hue_profile, area_profile = _profile_histograms(
        hue_histogram,
        area_hue_histogram,
    )
    matches = set()
    for span in MATCHING_SPANS:
        for center in WHEEL_CENTERS:
            if (
                math.isclose(
                    slice_coverage(hue_profile, center, span),
                    1.0,
                    abs_tol=1e-12,
                )
                and math.isclose(
                    slice_coverage(area_profile, center, span),
                    1.0,
                    abs_tol=1e-12,
                )
            ):
                matches.add((span, center))
    return matches


def catalog_slice_counts(artworks: list[Artwork]) -> dict[tuple[int, int], int]:
    counts = {
        (span, center): 0
        for span in MATCHING_SPANS
        for center in WHEEL_CENTERS
    }
    for artwork in artworks:
        for key in matching_slices(
            artwork.hue_histogram,
            artwork.area_hue_histogram,
        ):
            counts[key] += 1
    return counts


def _card_color(card: dict[str, object]) -> str | None:
    raw_identity = card.get("color_identity")
    if not isinstance(raw_identity, list) or len(raw_identity) > 1:
        return None
    if not raw_identity:
        return "C"
    color = raw_identity[0]
    return color if isinstance(color, str) and color in COLOR_TARGET_CENTERS else None


def _card_year(card: dict[str, object]) -> int:
    released_at = card.get("released_at")
    if isinstance(released_at, str):
        try:
            return int(released_at[:4])
        except ValueError:
            pass
    return 1993


def _era_start(year: int) -> int:
    return 1993 + max(0, year - 1993) // 5 * 5


def load_candidates(
    bulk_file: Path,
    existing_ids: set[str],
    existing_title_artists: set[tuple[str, str]],
    target_illustration_ids: set[str] | None = None,
    tagged_only: bool = False,
) -> list[Candidate]:
    target_ids = target_illustration_ids or set()
    buckets: dict[tuple[bool, int, str], deque[Candidate]] = defaultdict(deque)
    with gzip.open(bulk_file, "rt", encoding="utf-8") as stream:
        for line in stream:
            card = json.loads(line)
            if not isinstance(card, dict):
                continue
            games = card.get("games")
            if not isinstance(games, list) or "paper" not in games:
                continue
            if card.get("type_line") == "Card":
                continue
            illustration_id = card.get("illustration_id")
            tagged = isinstance(illustration_id, str) and illustration_id in target_ids
            if tagged_only and not tagged:
                continue
            color = _card_color(card)
            if color is None:
                if not tagged:
                    continue
                color = "C"
            record = ScryfallSource._record_from_card(card)
            if record is None or record.id in existing_ids:
                continue
            title_artist = (
                record.title.strip().casefold(),
                record.artist.strip().casefold(),
            )
            if title_artist in existing_title_artists:
                continue
            year = _card_year(card)
            buckets[(not tagged, _era_start(year), color)].append(
                Candidate(record=record, color=color, year=year, tagged=tagged)
            )

    ordered = []
    bucket_keys = sorted(buckets)
    while bucket_keys:
        remaining_keys = []
        for key in bucket_keys:
            bucket = buckets[key]
            if bucket:
                ordered.append(bucket.popleft())
            if bucket:
                remaining_keys.append(key)
        bucket_keys = remaining_keys
    return ordered


def load_target_illustration_ids(art_tags_file: Path) -> set[str]:
    illustration_ids = set()
    with gzip.open(art_tags_file, "rt", encoding="utf-8") as stream:
        for line in stream:
            tag = json.loads(line)
            if not isinstance(tag, dict) or tag.get("label") not in TARGET_ART_TAG_LABELS:
                continue
            taggings = tag.get("taggings")
            if not isinstance(taggings, list):
                continue
            for tagging in taggings:
                if not isinstance(tagging, dict):
                    continue
                illustration_id = tagging.get("illustration_id")
                if isinstance(illustration_id, str):
                    illustration_ids.add(illustration_id)
    return illustration_ids


def analyze_candidate(
    candidate: Candidate,
    client: httpx.Client,
) -> tuple[Candidate, ColorProfile | None, str | None]:
    try:
        response = client.get(candidate.record.analysis_url)
        response.raise_for_status()
        return candidate, analyze_image_bytes(response.content), None
    except (httpx.HTTPError, OSError, ValueError) as error:
        return candidate, None, str(error)


def _print_counts(label: str, counts: dict[tuple[int, int], int]) -> None:
    print(label)
    for matching_span in MATCHING_SPANS:
        display_span = matching_span + 15
        values = " ".join(
            f"{center:03d}:{counts[(matching_span, center)]}"
            for center in WHEEL_CENTERS
        )
        print(f"  {display_span}° {values}")


def main():
    args = parse_args()
    if not args.bulk_file.exists():
        raise SystemExit(f"Missing bulk file: {args.bulk_file}")
    if args.art_tags_file is not None and not args.art_tags_file.exists():
        raise SystemExit(f"Missing art tags file: {args.art_tags_file}")
    if args.tagged_only and args.art_tags_file is None:
        raise SystemExit("--tagged-only requires --art-tags-file")
    if not 0 < args.max_additions <= MAX_ADDITIONS:
        raise SystemExit(f"--max-additions must be between 1 and {MAX_ADDITIONS}")
    if args.target_minimum <= 0:
        raise SystemExit("--target-minimum must be positive")
    if args.scan_limit <= 0:
        raise SystemExit("--scan-limit must be positive")
    if args.workers <= 0:
        raise SystemExit("--workers must be positive")

    repository = ArtworkRepository(args.database_url)
    repository.initialize()
    artworks = repository.all_artworks()
    counts = catalog_slice_counts(artworks)
    _print_counts("Starting fixed-slice counts:", counts)
    existing_ids = {artwork.id for artwork in artworks}
    existing_title_artists = {
        (artwork.title.strip().casefold(), artwork.artist.strip().casefold())
        for artwork in artworks
        if artwork.source == "magic"
    }
    target_illustration_ids = (
        load_target_illustration_ids(args.art_tags_file)
        if args.art_tags_file is not None
        else set()
    )
    if target_illustration_ids:
        print(
            f"Loaded {len(target_illustration_ids)} illustrations with targeted color tags"
        )
    candidates = load_candidates(
        args.bulk_file,
        existing_ids,
        existing_title_artists,
        target_illustration_ids,
        args.tagged_only,
    )
    print(f"Loaded {len(candidates)} unique candidate illustrations")

    stored = 0
    scanned = 0
    failed = 0
    batch_size = args.workers * 3
    with build_http_client() as client:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            analyze = partial(analyze_candidate, client=client)
            for start in range(0, min(len(candidates), args.scan_limit), batch_size):
                if stored >= args.max_additions:
                    break
                underfilled = {
                    key for key, count in counts.items() if count < args.target_minimum
                }
                if not underfilled:
                    break
                useful_centers = {center for _, center in underfilled}
                batch = [
                    candidate
                    for candidate in candidates[start:start + batch_size]
                    if COLOR_TARGET_CENTERS[candidate.color] & useful_centers
                ]
                results = executor.map(analyze, batch)
                for candidate, profile, error in results:
                    scanned += 1
                    if profile is None:
                        failed += 1
                        print(f"Skipped {candidate.record.title}: {error}")
                        continue
                    if profile.colorfulness <= 0.01:
                        continue
                    matches = matching_slices(
                        profile.hue_histogram,
                        profile.area_hue_histogram,
                    )
                    improvements = {
                        key for key in matches if counts[key] < args.target_minimum
                    }
                    if not improvements:
                        continue
                    repository.upsert(
                        candidate.record,
                        profile.hue_histogram,
                        profile.area_hue_histogram,
                        profile.dominant_hue,
                        profile.colorfulness,
                    )
                    stored += 1
                    for key in matches:
                        counts[key] += 1
                    improved = ", ".join(
                        f"{span + 15}°@{center}°"
                        for span, center in sorted(improvements)
                    )
                    print(
                        f"Added {stored}: {candidate.record.title} ({candidate.year}) "
                        f"for {improved}"
                    )
                    if stored >= args.max_additions:
                        break
                print(
                    f"Progress: {scanned} analyzed, {stored} added, {failed} failed"
                )

    _print_counts("Final fixed-slice counts:", counts)
    print(
        f"Done: analyzed {scanned}, added {stored}, failed {failed}; "
        f"catalog now has {repository.count(('magic',))} Magic works"
    )


if __name__ == "__main__":
    main()
