from scripts.ingest_balanced_magic import ERAS, waterfill


def test_waterfill_balances_additions_around_existing_catalog():
    existing = {
        ERAS[0]: 11,
        ERAS[1]: 3,
        ERAS[2]: 0,
        ERAS[3]: 3,
        ERAS[4]: 11,
        ERAS[5]: 77,
        ERAS[6]: 395,
    }

    additions = waterfill(ERAS, existing, 2000)
    final_counts = [existing[era] + additions[era] for era in ERAS]

    assert sum(additions.values()) == 2000
    assert additions[ERAS[6]] == 0
    assert final_counts == [351, 351, 351, 351, 351, 350, 395]
