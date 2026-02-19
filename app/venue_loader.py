"""Load venues from Google Maps Places API into MongoDB."""

import asyncio
import sys
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.db import close_db, get_db, init_db

PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_NEARBY_SEARCH_URL = "https://places.googleapis.com/v1/places:searchNearby"
FIELDS = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.location,"
    "places.websiteUri,"
    "places.googleMapsUri,"
    "places.rating"
)

def _places_headers() -> dict:
    api_key = settings.google_maps_api_key
    if not api_key or api_key == "your-api-key-here":
        print("ERROR: Set GOOGLE_MAPS_API_KEY in .env")
        sys.exit(1)
    return {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELDS,
    }


# Text Search (New) returns up to 20 per page and supports pagination via nextPageToken.
TEXT_SEARCH_PAGE_SIZE = 20


async def search_places(query: str) -> list[dict]:
    """Search Google Maps Places API (new) for venues matching a query."""
    headers = _places_headers()
    body = {
        "textQuery": query,
        "languageCode": "ja",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(PLACES_TEXT_SEARCH_URL, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    return data.get("places", [])


async def search_places_text_in_rect(
    query: str,
    south: float,
    west: float,
    north: float,
    east: float,
    *,
    page_token: str | None = None,
) -> tuple[list[dict], str | None]:
    """Search text within a rectangular bounds; returns (places, next_page_token or None)."""
    headers = _places_headers()
    body = {
        "textQuery": query,
        "languageCode": "ja",
        "pageSize": TEXT_SEARCH_PAGE_SIZE,
        "locationRestriction": {
            "rectangle": {
                "low": {"latitude": south, "longitude": west},
                "high": {"latitude": north, "longitude": east},
            }
        },
    }
    if page_token:
        body["pageToken"] = page_token

    async with httpx.AsyncClient() as client:
        resp = await client.post(PLACES_TEXT_SEARCH_URL, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    places = data.get("places", [])
    next_token = data.get("nextPageToken") or None
    return places, next_token


async def search_places_text_in_rect_paginated(
    query: str,
    south: float,
    west: float,
    north: float,
    east: float,
    *,
    max_pages: int = 100,
) -> list[dict]:
    """Paginate through all text-search results in a rectangle until no next page or max_pages."""
    all_places: list[dict] = []
    page_token: str | None = None
    page = 0

    while page < max_pages:
        places, page_token = await search_places_text_in_rect(
            query, south, west, north, east, page_token=page_token
        )
        all_places.extend(places)
        page += 1
        if not page_token or not places:
            break

    return all_places


# Nearby Search (New) returns at most 20 results per request and has no pagination.
NEARBY_MAX_RESULT_COUNT = 20


async def search_nearby_places(
    latitude: float, longitude: float, radius_meters: float
) -> list[dict]:
    """Search Google Maps Places API (new) for venues near a point (e.g. live_music_venue).

    The API returns at most 20 results per request and does not support pagination.
    If you need more coverage, run multiple requests with different center points and
    merge/dedupe by google_place_id.
    """
    headers = _places_headers()
    body = {
        "includedTypes": ["live_music_venue"],
        "languageCode": "ja",
        "maxResultCount": NEARBY_MAX_RESULT_COUNT,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": latitude, "longitude": longitude},
                "radius": radius_meters,
            }
        },
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            PLACES_NEARBY_SEARCH_URL, json=body, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()

    return data.get("places", [])


def place_to_venue(place: dict) -> dict:
    """Convert a Google Places API result to our venue document format."""
    loc = place.get("location", {})
    return {
        "name": place.get("displayName", {}).get("text", "Unknown"),
        "google_place_id": place.get("id"),
        "location": {
            "type": "Point",
            "coordinates": [loc.get("longitude", 0), loc.get("latitude", 0)],
        },
        "address": place.get("formattedAddress", ""),
        "website": place.get("websiteUri"),
        "google_maps_url": place.get("googleMapsUri"),
        "rating": place.get("rating"),
        "schedule_url": None,
        "scraping_strategy": None,
        "scraping_instructions": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def _print_venues(venues: list[dict]) -> None:
    for i, venue in enumerate(venues, 1):
        coords = venue["location"]["coordinates"]
        print(f"  {i}. {venue['name']}")
        print(f"     Address: {venue['address']}")
        print(f"     Website: {venue['website'] or 'N/A'}")
        print(f"     Rating:  {venue['rating'] or 'N/A'}")
        print(f"     Coords:  {coords[1]:.4f}, {coords[0]:.4f}")
        print()


async def _upsert_venues(venues: list[dict]) -> tuple[int, int]:
    db = get_db()
    await init_db()
    saved = 0
    skipped = 0
    for venue in venues:
        created_at = venue.pop("created_at")
        result = await db.venues.update_one(
            {"google_place_id": venue["google_place_id"]},
            {
                "$set": venue,
                "$setOnInsert": {"created_at": created_at, "venue_state": "new"},
            },
            upsert=True,
        )
        if result.upserted_id:
            saved += 1
        else:
            skipped += 1
    return saved, skipped


async def load_venues(query: str, *, dry_run: bool = False) -> None:
    """Search for venues and upsert them into MongoDB."""
    print(f"Searching for: {query}")
    places = await search_places(query)

    if not places:
        print("No results found.")
        return

    print(f"\nFound {len(places)} venues:\n")
    venues = [place_to_venue(p) for p in places]
    _print_venues(venues)

    if dry_run:
        print("Dry run — nothing saved.")
        return

    answer = input("Save these venues to MongoDB? [y/N] ").strip().lower()
    if answer != "y":
        print("Cancelled.")
        return

    saved, skipped = await _upsert_venues(venues)
    print(f"\nDone: {saved} new, {skipped} already existed (updated).")


async def load_venues_nearby(
    latitude: float,
    longitude: float,
    radius_meters: float,
    *,
    dry_run: bool = False,
) -> None:
    """Find live_music_venue places near a point and upsert them into MongoDB."""
    print(
        f"Searching nearby: ({latitude:.4f}, {longitude:.4f}), radius {radius_meters}m (live_music_venue)"
    )
    places = await search_nearby_places(latitude, longitude, radius_meters)

    if not places:
        print("No results found.")
        return

    print(f"\nFound {len(places)} venues:\n")
    if len(places) == NEARBY_MAX_RESULT_COUNT:
        print(
            f"  (API limit: max {NEARBY_MAX_RESULT_COUNT} per request, no pagination — "
            "there may be more venues in this area.)\n"
        )
    venues = [place_to_venue(p) for p in places]
    _print_venues(venues)

    if dry_run:
        print("Dry run — nothing saved.")
        return

    answer = input("Save these venues to MongoDB? [y/N] ").strip().lower()
    if answer != "y":
        print("Cancelled.")
        return

    saved, skipped = await _upsert_venues(venues)
    print(f"\nDone: {saved} new, {skipped} already existed (updated).")


# Default query for rect search (general "live music" within the box).
LIVE_MUSIC_QUERY = "live music"


async def load_venues_rect(
    south: float,
    west: float,
    north: float,
    east: float,
    *,
    query: str = LIVE_MUSIC_QUERY,
    max_pages: int = 100,
    dry_run: bool = False,
) -> None:
    """Text-search for venues in a rectangular area with pagination, then upsert to MongoDB."""
    print(
        f"Searching text '{query}' in rectangle: south={south:.4f}, west={west:.4f}, "
        f"north={north:.4f}, east={east:.4f} (max {max_pages} pages)"
    )
    places = await search_places_text_in_rect_paginated(
        query, south, west, north, east, max_pages=max_pages
    )

    if not places:
        print("No results found.")
        return

    # Dedupe by place id (same place can appear across pages in theory)
    seen_ids: set[str] = set()
    unique_places: list[dict] = []
    for p in places:
        pid = p.get("id")
        if pid and pid not in seen_ids:
            seen_ids.add(pid)
            unique_places.append(p)

    print(f"\nFound {len(unique_places)} venues ({len(places)} raw with pagination):\n")
    venues = [place_to_venue(p) for p in unique_places]
    _print_venues(venues)

    if dry_run:
        print("Dry run — nothing saved.")
        return

    answer = input("Save these venues to MongoDB? [y/N] ").strip().lower()
    if answer != "y":
        print("Cancelled.")
        return

    saved, skipped = await _upsert_venues(venues)
    print(f"\nDone: {saved} new, {skipped} already existed (updated).")


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage:")
        print("  uv run -m app.venue_loader <search query>")
        print("  uv run -m app.venue_loader nearby <lat> <lng> <radius_meters>")
        print("  uv run -m app.venue_loader rect <south> <west> <north> <east> [max_pages]")
        print('Example: uv run -m app.venue_loader "ライブハウス 下北沢"')
        print("Example: uv run -m app.venue_loader nearby 35.6619 139.7038 5000")
        print("Example: uv run -m app.venue_loader rect 35.65 139.66 35.67 139.71 50")
        sys.exit(1)

    try:
        if sys.argv[1].lower() == "nearby":
            if len(sys.argv) < 5:
                print("Usage: uv run -m app.venue_loader nearby <lat> <lng> <radius_meters>")
                sys.exit(1)
            lat = float(sys.argv[2])
            lng = float(sys.argv[3])
            radius = float(sys.argv[4])
            await load_venues_nearby(lat, lng, radius)
        elif sys.argv[1].lower() == "rect":
            if len(sys.argv) < 6:
                print(
                    "Usage: uv run -m app.venue_loader rect <south> <west> <north> <east> [max_pages]"
                )
                sys.exit(1)
            south = float(sys.argv[2])
            west = float(sys.argv[3])
            north = float(sys.argv[4])
            east = float(sys.argv[5])
            max_pages = int(sys.argv[6]) if len(sys.argv) > 6 else 100
            await load_venues_rect(south, west, north, east, max_pages=max_pages)
        else:
            query = " ".join(sys.argv[1:])
            await load_venues(query)
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
