import gzip
import json

from colorslice.models import ArtworkRecord
from colorslice.repository import ArtworkRepository
from scripts.ingest_all_magic_art import (
    candidates_from_card,
    load_checkpoint,
    load_unique_candidates,
)


def image_uris(label):
    return {"art_crop": f"https://example.com/{label}.jpg"}


def card(card_id, illustration_id, *, name="Front", set_type="expansion"):
    return {
        "id": card_id,
        "illustration_id": illustration_id,
        "name": name,
        "artist": "Artist",
        "games": ["paper"],
        "set_type": set_type,
        "released_at": "2020-01-02",
        "image_uris": image_uris(illustration_id),
        "scryfall_uri": f"https://scryfall.com/{card_id}",
    }


def test_candidates_use_illustration_identity_and_include_both_faces():
    payload = card("card-id", "ignored")
    payload.pop("illustration_id")
    payload.pop("image_uris")
    payload["card_faces"] = [
        {
            "illustration_id": "front-art",
            "name": "Front",
            "artist": "Front Artist",
            "image_uris": image_uris("front"),
        },
        {
            "illustration_id": "back-art",
            "name": "Back",
            "artist": "Back Artist",
            "image_uris": image_uris("back"),
        },
    ]

    candidates = candidates_from_card(payload)

    assert [candidate.illustration_id for candidate in candidates] == [
        "front-art",
        "back-art",
    ]
    assert [candidate.record.title for candidate in candidates] == ["Front", "Back"]
    assert candidates[0].record.source_id == "illustration:front-art"


def test_bulk_loader_deduplicates_shared_illustrations(tmp_path):
    path = tmp_path / "cards.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for payload in (card("one", "same"), card("two", "same"), card("three", "new")):
            stream.write(json.dumps(payload) + "\n")

    candidates, card_illustrations = load_unique_candidates(path)

    assert set(candidates) == {"same", "new"}
    assert card_illustrations == {"one": "same", "two": "same", "three": "new"}


def test_checkpoint_resumes_stored_and_colorless_but_retries_failures(tmp_path):
    path = tmp_path / "checkpoint.jsonl"
    path.write_text(
        '\n'.join(
            (
                '{"illustration_id":"stored","status":"stored"}',
                '{"illustration_id":"blank","status":"colorless"}',
                '{"illustration_id":"retry","status":"failed"}',
                "not-json",
            )
        ),
        encoding="utf-8",
    )

    assert load_checkpoint(path) == {"stored", "blank"}


def test_repository_batches_artwork_upserts(tmp_path, monkeypatch):
    database_path = tmp_path / "batch.db"
    monkeypatch.setenv("COLORSLICE_DB_PATH", str(database_path))
    repository = ArtworkRepository()
    repository.initialize()
    histogram = tuple([1.0] + [0.0] * 71)
    records = [
        ArtworkRecord(
            source="magic",
            source_id=str(index),
            title=f"Work {index}",
            artist="Artist",
            year=2020,
            image_url=f"https://example.com/{index}.jpg",
            thumbnail_url=f"https://example.com/{index}.jpg",
            analysis_url=f"https://example.com/{index}.jpg",
            source_url=f"https://example.com/{index}",
            license_label="© Wizards of the Coast",
        )
        for index in range(3)
    ]

    repository.upsert_many(
        [(record, histogram, histogram, 2.5, 0.5) for record in records]
    )

    assert repository.count(("magic",)) == 3
