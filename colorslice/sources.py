from collections.abc import Iterator
from typing import Any

import httpx

from colorslice.models import ArtworkRecord, year_from_iso_date


USER_AGENT = "Colorslice/0.1 (MTG art palette matching tool; contact: colorslice app)"
SCRYFALL_SEARCH_URL = "https://api.scryfall.com/cards/search"


def _string(value: object, fallback: str = "") -> str:
    return value if isinstance(value, str) else fallback


class ScryfallSource:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def records(
        self,
        limit: int,
        *,
        query: str = "game:paper -is:funny",
        seen_titles: set[str] | None = None,
    ) -> Iterator[ArtworkRecord]:
        if limit <= 0:
            return
        title_keys = seen_titles if seen_titles is not None else set()
        url: str | None = SCRYFALL_SEARCH_URL
        parameters: dict[str, object] | None = {
            "q": query,
            "unique": "cards",
            "order": "edhrec",
            "dir": "asc",
        }
        yielded = 0
        while url and yielded < limit:
            response = self.client.get(url, params=parameters)
            response.raise_for_status()
            payload = response.json()
            for card in payload.get("data", []):
                if yielded >= limit:
                    return
                record = self._record_from_card(card)
                if record is None:
                    continue
                title_key = record.title.strip().casefold()
                if title_key in title_keys:
                    continue
                title_keys.add(title_key)
                yielded += 1
                yield record
            next_page = payload.get("next_page")
            url = next_page if isinstance(next_page, str) else None
            parameters = None

    @staticmethod
    def _record_from_card(card: dict[str, Any]) -> ArtworkRecord | None:
        image_uris = card.get("image_uris")
        card_face = card
        if not isinstance(image_uris, dict):
            faces = card.get("card_faces")
            if not isinstance(faces, list) or not faces:
                return None
            first_face = faces[0]
            if not isinstance(first_face, dict):
                return None
            image_uris = first_face.get("image_uris")
            card_face = first_face
        if not isinstance(image_uris, dict):
            return None

        art_crop = _string(image_uris.get("art_crop"))
        normal = _string(image_uris.get("normal"))
        small = _string(image_uris.get("small"))
        if not art_crop or not normal:
            return None
        source_id = _string(card.get("id"))
        if not source_id:
            return None
        artist = _string(card_face.get("artist")) or _string(card.get("artist"), "Unknown artist")
        title = _string(card_face.get("name")) or _string(card.get("name"), "Untitled")
        return ArtworkRecord(
            source="magic",
            source_id=source_id,
            title=title,
            artist=artist,
            year=year_from_iso_date(_string(card.get("released_at")) or None),
            image_url=art_crop,
            thumbnail_url=art_crop or small or normal,
            analysis_url=art_crop,
            source_url=_string(card.get("scryfall_uri"), _string(card.get("uri"))),
            license_label="© Wizards of the Coast",
        )


def build_http_client() -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(35.0),
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, image/avif, image/webp, image/*;q=0.9, */*;q=0.8",
        },
    )
