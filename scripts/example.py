"""Example custom script — copy this as a starting point for new venues.

Venue config in MongoDB::

    {
        "scraping_strategy": "custom",
        "custom_script": "example",
        "custom_kwargs": {"some_option": true}
    }
"""

from app.models import Event
from app.scraper import crawl_page
from app.extractor import extract_events


async def run(venue: dict, *, use_cache: bool = True, **kwargs) -> list[Event]:
    """Custom scraping logic — replace with venue-specific implementation."""
    venue_id = str(venue["_id"])
    venue_name = venue["name"]
    url = venue.get("schedule_url") or kwargs.get("url")

    if not url:
        print(f"[{venue_name}] No URL provided")
        return []

    content = await crawl_page(url, use_cache=use_cache)
    events = await extract_events(content, venue_id, venue_name)
    return events
