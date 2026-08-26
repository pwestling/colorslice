from argparse import ArgumentParser
from collections import defaultdict
import gzip
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from colorslice.repository import ArtworkRepository


def parse_args():
    parser = ArgumentParser(
        description="Attach every indexed Magic illustration to its printed sets."
    )
    parser.add_argument("--bulk-file", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=5_000)
    parser.add_argument("--export-bundle", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    return parser.parse_args()


def _string(value: object, fallback: str = "") -> str:
    return value if isinstance(value, str) else fallback


def _image_key(value: str) -> str:
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _faces(card: dict[str, object]) -> tuple[dict[str, object], ...]:
    if isinstance(card.get("image_uris"), dict):
        return (card,)
    raw_faces = card.get("card_faces")
    if not isinstance(raw_faces, list):
        return ()
    return tuple(face for face in raw_faces if isinstance(face, dict))


def collect_artwork_set_links(
    bulk_file: Path,
    metadata_keys: list[tuple[str, str, str]],
    include_unindexed_illustrations: bool = False,
) -> list[tuple[str, str, str, str | None]]:
    artwork_ids = {artwork_id for artwork_id, _, _ in metadata_keys}
    source_ids = {
        source_id: artwork_id
        for artwork_id, source_id, _ in metadata_keys
    }
    image_urls = {
        _image_key(image_url): artwork_id
        for artwork_id, _, image_url in metadata_keys
    }
    illustration_artworks: dict[str, set[str]] = defaultdict(set)
    for artwork_id, source_id, _ in metadata_keys:
        if source_id.startswith("illustration:"):
            illustration_artworks[
                source_id.removeprefix("illustration:")
            ].add(artwork_id)
    illustration_sets: dict[
        str,
        set[tuple[str, str, str | None]],
    ] = defaultdict(set)

    with gzip.open(bulk_file, "rt", encoding="utf-8") as stream:
        for line in stream:
            card = json.loads(line)
            if not isinstance(card, dict):
                continue
            set_code = _string(card.get("set")).lower()
            set_name = _string(card.get("set_name"))
            released_at = _string(card.get("released_at")) or None
            if not set_code or not set_name:
                continue
            card_id = _string(card.get("id"))
            card_artwork_id = source_ids.get(card_id)

            for face in _faces(card):
                illustration_id = _string(face.get("illustration_id"))
                if not illustration_id:
                    continue
                illustration_sets[illustration_id].add(
                    (set_code, set_name, released_at)
                )
                direct_id = f"magic:illustration:{illustration_id}"
                if direct_id in artwork_ids or include_unindexed_illustrations:
                    illustration_artworks[illustration_id].add(direct_id)
                if card_artwork_id is not None:
                    illustration_artworks[illustration_id].add(card_artwork_id)
                image_uris = face.get("image_uris")
                if not isinstance(image_uris, dict):
                    continue
                art_crop = _string(image_uris.get("art_crop"))
                image_artwork_id = image_urls.get(_image_key(art_crop))
                if image_artwork_id is not None:
                    illustration_artworks[illustration_id].add(image_artwork_id)

    return sorted(
        (
            artwork_id,
            set_code,
            set_name,
            released_at,
        )
        for illustration_id, artwork_ids_for_illustration in illustration_artworks.items()
        for artwork_id in artwork_ids_for_illustration
        for set_code, set_name, released_at in illustration_sets[illustration_id]
    )


def export_bundle(
    path: Path,
    links: list[tuple[str, str, str, str | None]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as stream:
        for link in links:
            stream.write(json.dumps(link, separators=(",", ":")) + "\n")


def main():
    args = parse_args()
    if not args.bulk_file.exists():
        raise SystemExit(f"Missing bulk file: {args.bulk_file}")
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be positive")

    repository = ArtworkRepository(args.database_url)
    repository.initialize()
    metadata_keys = repository.artwork_metadata_keys()
    links = collect_artwork_set_links(args.bulk_file, metadata_keys)
    linked_artworks = len({artwork_id for artwork_id, _, _, _ in links})
    print(
        f"Resolved {len(links):,} artwork/set links for "
        f"{linked_artworks:,} of {len(metadata_keys):,} Magic artworks."
    )
    if args.export_bundle is not None:
        bundle_links = collect_artwork_set_links(
            args.bulk_file,
            metadata_keys,
            include_unindexed_illustrations=True,
        )
        export_bundle(args.export_bundle, bundle_links)
        print(
            f"Exported {len(bundle_links):,} candidate artwork/set links to "
            f"{args.export_bundle}."
        )
    if args.dry_run:
        return

    stored = 0
    for start in range(0, len(links), args.batch_size):
        stored += repository.upsert_artwork_sets(
            links[start:start + args.batch_size]
        )
    print(f"Stored {stored:,} artwork/set links.")


if __name__ == "__main__":
    main()
