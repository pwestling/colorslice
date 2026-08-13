from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from dataclasses import asdict
from functools import partial
import gzip
import json
import os
from pathlib import Path
import time

import httpx

from colorslice.color import ColorProfile, analyze_image_bytes
from colorslice.models import ArtworkRecord, year_from_iso_date
from colorslice.repository import ArtworkRepository
from colorslice.sources import build_http_client


DEFAULT_CHECKPOINT = Path("data/downloads/magic-art-checkpoint.jsonl")
EXCLUDED_SET_TYPES = frozenset(("funny", "memorabilia", "minigame", "token"))


@dataclass(frozen=True, slots=True)
class IllustrationCandidate:
    illustration_id: str
    record: ArtworkRecord


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    candidate: IllustrationCandidate
    profile: ColorProfile | None
    error: str | None


def parse_args():
    parser = ArgumentParser(
        description="Import every unique official paper Magic illustration."
    )
    parser.add_argument("--bulk-file", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--upload-url")
    parser.add_argument(
        "--upload-token",
        default=os.environ.get("COLORSLICE_IMPORT_TOKEN"),
    )
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    return parser.parse_args()


def _string(value: object, fallback: str = "") -> str:
    return value if isinstance(value, str) else fallback


def _candidate_from_face(
    card: dict[str, object],
    face: dict[str, object],
) -> IllustrationCandidate | None:
    illustration_id = face.get("illustration_id")
    image_uris = face.get("image_uris")
    if not isinstance(illustration_id, str) or not isinstance(image_uris, dict):
        return None

    art_crop = _string(image_uris.get("art_crop"))
    if not art_crop:
        return None
    artist = _string(face.get("artist")) or _string(card.get("artist"), "Unknown artist")
    title = _string(face.get("name")) or _string(card.get("name"), "Untitled")
    record = ArtworkRecord(
        source="magic",
        source_id=f"illustration:{illustration_id}",
        title=title,
        artist=artist,
        year=year_from_iso_date(_string(card.get("released_at")) or None),
        image_url=art_crop,
        thumbnail_url=art_crop,
        analysis_url=art_crop,
        source_url=_string(card.get("scryfall_uri"), _string(card.get("uri"))),
        license_label="© Wizards of the Coast",
    )
    return IllustrationCandidate(illustration_id=illustration_id, record=record)


def candidates_from_card(card: dict[str, object]) -> tuple[IllustrationCandidate, ...]:
    games = card.get("games")
    if not isinstance(games, list) or "paper" not in games:
        return ()
    if card.get("set_type") in EXCLUDED_SET_TYPES:
        return ()

    if isinstance(card.get("image_uris"), dict):
        candidate = _candidate_from_face(card, card)
        return (candidate,) if candidate is not None else ()

    faces = card.get("card_faces")
    if not isinstance(faces, list):
        return ()
    return tuple(
        candidate
        for face in faces
        if isinstance(face, dict)
        for candidate in (_candidate_from_face(card, face),)
        if candidate is not None
    )


def load_unique_candidates(
    bulk_file: Path,
) -> tuple[dict[str, IllustrationCandidate], dict[str, str]]:
    candidates: dict[str, IllustrationCandidate] = {}
    card_illustrations: dict[str, str] = {}
    with gzip.open(bulk_file, "rt", encoding="utf-8") as stream:
        for line in stream:
            card = json.loads(line)
            if not isinstance(card, dict):
                continue
            card_candidates = candidates_from_card(card)
            if not card_candidates:
                continue
            card_id = card.get("id")
            if isinstance(card_id, str):
                card_illustrations[card_id] = card_candidates[0].illustration_id
            for candidate in card_candidates:
                candidates.setdefault(candidate.illustration_id, candidate)
    return candidates, card_illustrations


def load_checkpoint(path: Path) -> set[str]:
    if not path.exists():
        return set()
    completed = set()
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            illustration_id = entry.get("illustration_id")
            status = entry.get("status")
            if isinstance(illustration_id, str) and status in {"stored", "colorless"}:
                completed.add(illustration_id)
    return completed


def append_checkpoint(
    path: Path,
    entries: list[tuple[str, str, str | None]],
) -> None:
    if not entries:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for illustration_id, status, error in entries:
            stream.write(
                json.dumps(
                    {
                        "illustration_id": illustration_id,
                        "status": status,
                        "error": error,
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
        stream.flush()


def analyze_candidate(
    candidate: IllustrationCandidate,
    client: httpx.Client,
) -> AnalysisResult:
    last_error = None
    for attempt in range(3):
        try:
            response = client.get(candidate.record.analysis_url)
            response.raise_for_status()
            return AnalysisResult(
                candidate=candidate,
                profile=analyze_image_bytes(response.content),
                error=None,
            )
        except (httpx.HTTPError, OSError, ValueError) as error:
            last_error = str(error)
            if attempt < 2:
                time.sleep(0.5 * (2**attempt))
    return AnalysisResult(candidate=candidate, profile=None, error=last_error)


def upload_entries(
    client: httpx.Client,
    upload_url: str,
    upload_token: str,
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
    payload_entries = [
        {
            "record": asdict(record),
            "hue_histogram": hue_histogram,
            "area_hue_histogram": area_hue_histogram,
            "dominant_hue": dominant_hue,
            "colorfulness": colorfulness,
        }
        for (
            record,
            hue_histogram,
            area_hue_histogram,
            dominant_hue,
            colorfulness,
        ) in entries
    ]
    for attempt in range(3):
        try:
            response = client.post(
                upload_url,
                headers={"x-colorslice-import-token": upload_token},
                json={"entries": payload_entries},
                timeout=60.0,
            )
            response.raise_for_status()
            result = response.json()
            accepted = len(result.get("stored", [])) + len(result.get("existing", []))
            if accepted != len(entries):
                raise ValueError("Import endpoint did not accept the complete batch")
            return
        except (httpx.HTTPError, ValueError):
            if attempt == 2:
                raise
            time.sleep(1.0 * (2**attempt))


def _existing_illustration_ids(
    repository: ArtworkRepository,
    card_illustrations: dict[str, str],
    candidates: dict[str, IllustrationCandidate],
) -> set[str]:
    existing = set()
    illustration_by_url = {
        candidate.record.image_url: illustration_id
        for illustration_id, candidate in candidates.items()
    }
    for artwork in repository.all_artworks():
        if artwork.source != "magic":
            continue
        if artwork.source_id.startswith("illustration:"):
            existing.add(artwork.source_id.removeprefix("illustration:"))
        mapped = card_illustrations.get(artwork.source_id)
        if mapped is not None:
            existing.add(mapped)
        mapped = illustration_by_url.get(artwork.image_url)
        if mapped is not None:
            existing.add(mapped)
    return existing


def main():
    args = parse_args()
    if not args.bulk_file.exists():
        raise SystemExit(f"Missing bulk file: {args.bulk_file}")
    if args.workers <= 0:
        raise SystemExit("--workers must be positive")
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be positive")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be positive")
    if bool(args.upload_url) != bool(args.upload_token):
        raise SystemExit("--upload-url and --upload-token must be provided together")

    repository = ArtworkRepository(args.database_url)
    repository.initialize()
    candidates, card_illustrations = load_unique_candidates(args.bulk_file)
    existing = _existing_illustration_ids(repository, card_illustrations, candidates)
    completed = load_checkpoint(args.checkpoint)
    pending = [
        candidate
        for illustration_id, candidate in candidates.items()
        if illustration_id not in existing and illustration_id not in completed
    ]
    if args.limit is not None:
        pending = pending[:args.limit]

    print(
        f"Bulk snapshot has {len(candidates)} unique paper illustrations; "
        f"{len(existing)} are already represented, {len(completed)} are checkpointed, "
        f"and {len(pending)} are pending"
    )
    if args.dry_run or not pending:
        return

    stored = 0
    colorless = 0
    failed = 0
    started_at = time.monotonic()
    with build_http_client() as client:
        analyze = partial(analyze_candidate, client=client)
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            for start in range(0, len(pending), args.batch_size):
                batch = pending[start:start + args.batch_size]
                results = list(executor.map(analyze, batch))
                inserts = []
                checkpoint_entries = []
                for result in results:
                    illustration_id = result.candidate.illustration_id
                    if result.profile is None:
                        failed += 1
                        checkpoint_entries.append(
                            (illustration_id, "failed", result.error)
                        )
                        continue
                    if result.profile.colorfulness <= 0.01:
                        colorless += 1
                        checkpoint_entries.append((illustration_id, "colorless", None))
                        continue
                    inserts.append(
                        (
                            result.candidate.record,
                            result.profile.hue_histogram,
                            result.profile.area_hue_histogram,
                            result.profile.dominant_hue,
                            result.profile.colorfulness,
                        )
                    )
                    checkpoint_entries.append((illustration_id, "stored", None))

                if inserts and args.upload_url and args.upload_token:
                    upload_entries(
                        client,
                        args.upload_url,
                        args.upload_token,
                        inserts,
                    )
                elif inserts:
                    repository.upsert_many(inserts)
                append_checkpoint(args.checkpoint, checkpoint_entries)
                stored += len(inserts)
                processed = min(start + len(batch), len(pending))
                elapsed = max(0.001, time.monotonic() - started_at)
                rate = processed / elapsed
                remaining_minutes = (len(pending) - processed) / max(rate, 0.001) / 60
                print(
                    f"Processed {processed}/{len(pending)}: {stored} stored, "
                    f"{colorless} colorless, {failed} failed; "
                    f"{rate:.1f}/s, approximately {remaining_minutes:.1f} minutes remaining",
                    flush=True,
                )

    print(
        f"Done: {stored} stored, {colorless} colorless, {failed} failed; "
        f"catalog now has {repository.count(('magic',))} Magic works"
    )


if __name__ == "__main__":
    main()
