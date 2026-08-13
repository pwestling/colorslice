import gzip
import json

from scripts.ingest_targeted_magic import (
    _card_color,
    load_target_illustration_ids,
    matching_slices,
)


def histogram_at(index):
    return tuple(1.0 if candidate == index else 0.0 for candidate in range(72))


def test_matching_slices_finds_only_containing_fixed_arcs():
    blue = histogram_at(44)

    matches = matching_slices(blue, blue)

    assert (75, 210) in matches
    assert (105, 210) in matches
    assert (75, 75) not in matches


def test_targeted_importer_uses_only_zero_or_one_color_identities():
    assert _card_color({"color_identity": []}) == "C"
    assert _card_color({"color_identity": ["U"]}) == "U"
    assert _card_color({"color_identity": ["U", "B"]}) is None


def test_art_tag_loader_selects_only_targeted_color_tags(tmp_path):
    path = tmp_path / "tags.jsonl.gz"
    tags = (
        {
            "label": "pink background",
            "taggings": [{"illustration_id": "wanted"}],
        },
        {
            "label": "dragon",
            "taggings": [{"illustration_id": "ignored"}],
        },
    )
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for tag in tags:
            stream.write(json.dumps(tag) + "\n")

    assert load_target_illustration_ids(path) == {"wanted"}
