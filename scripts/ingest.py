from argparse import ArgumentParser
import os

import httpx

from colorslice.color import analyze_image_bytes
from colorslice.repository import ArtworkRepository
from colorslice.sources import ScryfallSource, build_http_client


def parse_args():
    parser = ArgumentParser(description="Ingest MTG art and compute OKLCH hue profiles.")
    parser.add_argument("--limit", type=int, default=80, help="Maximum artworks")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    return parser.parse_args()


def ingest_source(name, records, repository, client, target=None):
    stored = 0
    skipped = 0
    for index, record in enumerate(records, start=1):
        try:
            response = client.get(record.analysis_url)
            response.raise_for_status()
            profile = analyze_image_bytes(response.content)
            if profile.colorfulness <= 0.01:
                skipped += 1
                continue
            repository.upsert(
                record,
                profile.hue_histogram,
                profile.area_hue_histogram,
                profile.dominant_hue,
                profile.colorfulness,
            )
            stored += 1
            print(f"[{name} {index}] {record.title} — {record.artist}")
            if target is not None and stored >= target:
                break
        except (httpx.HTTPError, OSError, ValueError) as error:
            skipped += 1
            print(f"[{name} {index}] skipped {record.title}: {error}")
    return stored, skipped


def main():
    args = parse_args()
    if args.limit <= 0:
        raise SystemExit("--limit must be positive")

    repository = ArtworkRepository(args.database_url)
    repository.initialize()
    totals = {"stored": 0, "skipped": 0}
    with build_http_client() as client:
        records = ScryfallSource(client).records(args.limit)
        stored, skipped = ingest_source("magic", records, repository, client)
        totals["stored"] += stored
        totals["skipped"] += skipped

    counts = repository.source_counts()
    print(
        f"Done: {totals['stored']} stored, {totals['skipped']} skipped. "
        f"Catalog now has {sum(counts.values())} works: {counts}"
    )


if __name__ == "__main__":
    main()
