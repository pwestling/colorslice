from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import date
import os

from colorslice.repository import ArtworkRepository
from colorslice.sources import ScryfallSource, build_http_client
from scripts.ingest import ingest_source


@dataclass(frozen=True, slots=True)
class Era:
    label: str
    start_year: int
    end_year: int

    @property
    def years(self) -> tuple[int, ...]:
        return tuple(range(self.start_year, self.end_year))


ERAS = (
    Era("1993–1997", 1993, 1998),
    Era("1998–2002", 1998, 2003),
    Era("2003–2007", 2003, 2008),
    Era("2008–2012", 2008, 2013),
    Era("2013–2017", 2013, 2018),
    Era("2018–2022", 2018, 2023),
    Era("2023–present", 2023, date.today().year + 1),
)


def parse_args():
    parser = ArgumentParser(
        description="Add Magic art while balancing the catalog across release eras."
    )
    parser.add_argument("--add", type=int, default=2000)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    return parser.parse_args()


def waterfill(keys, existing_counts, additions):
    ordered_keys = tuple(keys)
    order = {key: index for index, key in enumerate(ordered_keys)}
    quotas = {key: 0 for key in ordered_keys}
    for _ in range(additions):
        selected = min(
            ordered_keys,
            key=lambda key: (existing_counts.get(key, 0) + quotas[key], order[key]),
        )
        quotas[selected] += 1
    return quotas


def era_for_year(year):
    for era in ERAS:
        if era.start_year <= year < era.end_year:
            return era
    return None


def main():
    args = parse_args()
    if args.add <= 0:
        raise SystemExit("--add must be positive")

    repository = ArtworkRepository(args.database_url)
    repository.initialize()
    starting_count = repository.count(("magic",))
    year_counts = repository.source_year_counts("magic")
    era_counts = {era: 0 for era in ERAS}
    for year, count in year_counts.items():
        era = era_for_year(year)
        if era is not None:
            era_counts[era] += count

    era_quotas = waterfill(ERAS, era_counts, args.add)
    seen_titles = repository.source_titles("magic")
    print("Planned additions by era:")
    for era in ERAS:
        print(f"  {era.label}: {era_quotas[era]}")

    with build_http_client() as client:
        source = ScryfallSource(client)
        for era in ERAS:
            era_target = era_quotas[era]
            if era_target == 0:
                continue
            year_quotas = waterfill(era.years, year_counts, era_target)
            for year in era.years:
                target = year_quotas[year]
                if target == 0:
                    continue
                query = (
                    "game:paper -is:funny "
                    f"date>={year}-01-01 date<{year + 1}-01-01"
                )
                buffer = max(20, target // 5)
                records = source.records(
                    target + buffer,
                    query=query,
                    seen_titles=seen_titles,
                )
                stored, skipped = ingest_source(
                    f"magic {year}",
                    records,
                    repository,
                    client,
                    target=target,
                )
                if stored != target:
                    raise SystemExit(
                        f"Could only store {stored} of {target} requested works for {year} "
                        f"({skipped} skipped)"
                    )

    final_count = repository.count(("magic",))
    expected_count = starting_count + args.add
    if final_count != expected_count:
        raise SystemExit(f"Expected {expected_count} Magic works, found {final_count}")
    print(f"Done: Magic catalog grew from {starting_count} to {final_count} works")


if __name__ == "__main__":
    main()
