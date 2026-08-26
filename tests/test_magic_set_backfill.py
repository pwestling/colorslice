import gzip
import json

from scripts.backfill_magic_sets import collect_artwork_set_links


def test_backfill_links_one_illustration_to_every_printed_set(tmp_path):
    bulk_file = tmp_path / "cards.jsonl.gz"
    cards = [
        {
            "id": "stored-card-id",
            "name": "Example Card",
            "games": ["paper"],
            "set": "one",
            "set_name": "First Set",
            "set_type": "expansion",
            "released_at": "2000-01-01",
            "illustration_id": "shared-illustration",
            "image_uris": {"art_crop": "https://img.example/art.jpg?old"},
        },
        {
            "id": "reprint-card-id",
            "name": "Example Card",
            "games": ["paper"],
            "set": "two",
            "set_name": "Second Set",
            "set_type": "masters",
            "released_at": "2010-01-01",
            "illustration_id": "shared-illustration",
            "image_uris": {"art_crop": "https://img.example/art.jpg?new"},
        },
        {
            "id": "digital-card-id",
            "name": "Example Card",
            "games": ["arena"],
            "set": "three",
            "set_name": "Digital Set",
            "set_type": "token",
            "released_at": "2020-01-01",
            "illustration_id": "shared-illustration",
            "image_uris": {"art_crop": "https://img.example/art.jpg?digital"},
        },
    ]
    with gzip.open(bulk_file, "wt", encoding="utf-8") as stream:
        for card in cards:
            stream.write(json.dumps(card) + "\n")

    links = collect_artwork_set_links(
        bulk_file,
        [
            (
                "magic:stored-card-id",
                "stored-card-id",
                "https://img.example/art.jpg?indexed",
            )
        ],
    )

    assert links == [
        ("magic:stored-card-id", "one", "First Set", "2000-01-01"),
        ("magic:stored-card-id", "three", "Digital Set", "2020-01-01"),
        ("magic:stored-card-id", "two", "Second Set", "2010-01-01"),
    ]
