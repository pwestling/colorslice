from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
import itertools
from typing import Any

import httpx

from colorslice.models import ArtworkRecord, year_from_iso_date


USER_AGENT = "Colorslice/0.1 (human-made art palette reference; contact: colorslice app)"
SCRYFALL_SEARCH_URL = "https://api.scryfall.com/cards/search"
MET_SEARCH_URL = "https://collectionapi.metmuseum.org/public/collection/v1/search"
MET_OBJECT_URL = "https://collectionapi.metmuseum.org/public/collection/v1/objects/{object_id}"


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


class MetSource:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def records(self, limit: int) -> Iterator[ArtworkRecord]:
        if limit <= 0:
            return
        response = self.client.get(
            MET_SEARCH_URL,
            params={"hasImages": "true", "isHighlight": "true", "q": "painting"},
        )
        response.raise_for_status()
        object_ids = response.json().get("objectIDs") or []
        fetch_count = min(len(object_ids), max(limit * 3, limit))
        with ThreadPoolExecutor(max_workers=8) as executor:
            payloads = executor.map(self._fetch_object, object_ids[:fetch_count])
            records = (self._record_from_object(payload) for payload in payloads if payload)
            yield from itertools.islice((record for record in records if record), limit)

    def _fetch_object(self, object_id: int) -> dict[str, Any] | None:
        response = self.client.get(MET_OBJECT_URL.format(object_id=object_id))
        if response.status_code != 200:
            return None
        payload = response.json()
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _record_from_object(payload: dict[str, Any]) -> ArtworkRecord | None:
        if not payload.get("isPublicDomain"):
            return None
        primary_image = _string(payload.get("primaryImage"))
        small_image = _string(payload.get("primaryImageSmall"))
        if not primary_image and not small_image:
            return None
        object_id = payload.get("objectID")
        if not isinstance(object_id, int):
            return None
        begin_date = payload.get("objectBeginDate")
        year = begin_date if isinstance(begin_date, int) and begin_date != 0 else None
        artist = _string(payload.get("artistDisplayName")).strip()
        if not artist:
            artist = _string(payload.get("culture")).strip() or "Unknown artist"
        return ArtworkRecord(
            source="met",
            source_id=str(object_id),
            title=_string(payload.get("title"), "Untitled"),
            artist=artist,
            year=year,
            image_url=primary_image or small_image,
            thumbnail_url=small_image or primary_image,
            analysis_url=small_image or primary_image,
            source_url=_string(payload.get("objectURL")),
            license_label="Public Domain · The Met",
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
