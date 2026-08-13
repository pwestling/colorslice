from argparse import ArgumentParser
from pathlib import Path
import sqlite3


def parse_args():
    parser = ArgumentParser(description="Export a compact SQLite catalog for deployment.")
    parser.add_argument("--source", type=Path, default=Path("data/colorslice.db"))
    parser.add_argument("--destination", type=Path, default=Path("data/seed.db"))
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.source.exists():
        raise SystemExit(f"Missing source database: {args.source}")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(args.source) as source:
        with sqlite3.connect(args.destination) as destination:
            source.backup(destination)
            destination.execute("VACUUM")
    print(f"Exported {args.destination} ({args.destination.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
