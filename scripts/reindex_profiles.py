from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import os

import httpx

from colorslice.color import ColorProfile, analyze_image_bytes
from colorslice.models import Artwork
from colorslice.repository import CATALOG_PROFILE_VERSION, ArtworkRepository
from colorslice.sources import build_http_client


def parse_args():
    parser = ArgumentParser(
        description="Recompute chroma- and area-weighted hue profiles."
    )
    parser.add_argument("--source", choices=("all", "magic", "met"), default="all")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    return parser.parse_args()


def analyze_artwork(
    artwork: Artwork,
    *,
    client: httpx.Client,
) -> tuple[Artwork, ColorProfile | None, str | None]:
    try:
        response = client.get(artwork.thumbnail_url)
        response.raise_for_status()
        return artwork, analyze_image_bytes(response.content), None
    except (httpx.HTTPError, OSError, ValueError) as error:
        return artwork, None, str(error)


def main():
    args = parse_args()
    if args.workers <= 0:
        raise SystemExit("--workers must be positive")
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be positive")

    repository = ArtworkRepository(args.database_url)
    repository.initialize()
    artworks = repository.all_artworks()
    if args.source != "all":
        artworks = [artwork for artwork in artworks if artwork.source == args.source]

    stored = 0
    failures = []
    updates = []
    with build_http_client() as client:
        analyze = partial(analyze_artwork, client=client)
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            for artwork, profile, error in executor.map(analyze, artworks):
                if profile is None:
                    failures.append((artwork, error or "Unknown error"))
                    print(f"Skipped {artwork.title}: {failures[-1][1]}")
                    continue
                updates.append(
                    (
                        artwork.id,
                        profile.hue_histogram,
                        profile.area_hue_histogram,
                        profile.dominant_hue,
                        profile.colorfulness,
                    )
                )
                if len(updates) >= args.batch_size:
                    repository.update_profiles(updates)
                    stored += len(updates)
                    updates.clear()
                    print(f"Reindexed {stored}/{len(artworks)} artworks")

    repository.update_profiles(updates)
    stored += len(updates)
    print(f"Done: {stored} reindexed, {len(failures)} skipped")
    if failures:
        raise SystemExit("Some artworks could not be reindexed")
    repository.set_catalog_profile_version(CATALOG_PROFILE_VERSION)


if __name__ == "__main__":
    main()
