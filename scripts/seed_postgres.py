from argparse import ArgumentParser
import os
from pathlib import Path

from colorslice.repository import ArtworkRepository


def parse_args():
    parser = ArgumentParser(description="Copy the bundled SQLite catalog to Postgres.")
    parser.add_argument("--source", type=Path, default=Path("data/seed.db"))
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL is required")
    if not args.source.exists():
        raise SystemExit(f"Missing source database: {args.source}")

    repository = ArtworkRepository(args.database_url)
    repository.initialize()
    counts = repository.seed_from_sqlite(args.source)

    print(f"Seeded {sum(counts.values())} artworks into Postgres: {counts}")


if __name__ == "__main__":
    main()
