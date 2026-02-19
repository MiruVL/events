"""Full scraping pipeline: crawl venues, extract events, save to MongoDB."""

import asyncio
import importlib
import json
import sys
from datetime import datetime
from typing import Any

from app.db import close_db, get_db, init_db
from app.extractor import extract_events, extract_events_combined, extract_links
from app.models import Event, ScrapingStrategy, VenueState
from app.scraper import crawl_detail_pages, crawl_page, crawl_schedule


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_TEMPLATE_MONTHS = 3


def _add_months(dt: datetime, months: int) -> datetime:
    """Return a new datetime with *months* added (stdlib only)."""
    y, m = dt.year, dt.month
    m += months
    while m > 12:
        y += 1
        m -= 12
    while m < 1:
        y -= 1
        m += 12
    return dt.replace(year=y, month=m, day=1)


def _url_is_templated(url: str) -> bool:
    return "{" in url


def resolve_schedule_url(template: str, now: datetime | None = None) -> str:
    """
    Resolve a schedule URL template into a concrete URL.

    Supported placeholders (Python str.format syntax):
        {year}      -> 4-digit year, e.g. 2026
        {month}     -> month as int, e.g. 2
        {month:02d} -> zero-padded month, e.g. 02

    If the template contains no placeholders it is returned as-is.
    """
    if not _url_is_templated(template):
        return template
    if now is None:
        now = datetime.now()
    return template.format(year=now.year, month=now.month)


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


async def _save_events(events: list[Event]) -> int:
    """Save events to MongoDB, handling deduplication via upsert."""
    db = get_db()
    saved = 0

    for event in events:
        doc = event.model_dump()
        try:
            result = await db.events.update_one(
                {
                    "venue_id": doc["venue_id"],
                    "date": doc["date"],
                    "title": doc["title"],
                },
                {"$set": doc},
                upsert=True,
            )
            if result.upserted_id or result.modified_count:
                saved += 1
        except Exception as e:
            print(f"  Warning: failed to save event '{doc.get('title')}': {e}")

    return saved


# ---------------------------------------------------------------------------
# Strategy: schedule
# ---------------------------------------------------------------------------


async def _run_schedule_strategy(
    venue: dict, *, use_cache: bool = True, months: int | None = None
) -> list[Event]:
    """
    Schedule strategy: crawl schedule page(s) and extract events via LLM.

    If the schedule URL is templated, iterates over *months* months
    (default ``DEFAULT_TEMPLATE_MONTHS``). Each month is a separate LLM call
    to preserve context length.
    """
    venue_id = str(venue["_id"])
    venue_name = venue["name"]
    schedule_url_template = venue["schedule_url"]
    instructions = venue.get("scraping_instructions")
    css_selector = venue.get("schedule_css_selector")
    json_css_schema = venue.get("schedule_json_css_schema")
    content_type = venue.get("content_type", "fit_markdown")
    is_json = json_css_schema is not None

    templated = _url_is_templated(schedule_url_template)
    if months is None:
        months = DEFAULT_TEMPLATE_MONTHS if templated else 1

    all_events: list[Event] = []
    now = datetime.now()

    for offset in range(months):
        target = _add_months(now, offset)
        month_label = f"{target.year}-{target.month:02d}"
        print(f"[{venue_name}] --- Month {month_label} (offset {offset}) ---")

        schedule_url = resolve_schedule_url(schedule_url_template, target)
        cache_key_suffix = month_label if templated else None

        if offset == 0:
            print(f"[{venue_name}] Schedule URL: {schedule_url}")

        content = await crawl_schedule(
            venue_name,
            schedule_url,
            use_cache=use_cache,
            cache_key_suffix=cache_key_suffix,
            css_selector=css_selector,
            json_css_schema=json_css_schema,
            content_type=content_type,
        )

        month_events = await extract_events(
            content,
            venue_id,
            venue_name,
            instructions,
            page_type="schedule",
            is_json=is_json,
        )

        for event in month_events:
            if not event.detail_url:
                event.detail_url = schedule_url

        all_events.extend(month_events)
        print(f"[{venue_name}] Month {month_label}: {len(month_events)} events.")

    return all_events


# ---------------------------------------------------------------------------
# Strategy: link_gathering
# ---------------------------------------------------------------------------


def _parse_links_from_json(json_content: str) -> list[str]:
    """
    Parse event links directly from JsonCssExtractionStrategy output.

    Expects the JSON to be a list of objects, each containing a ``url``,
    ``href``, ``link``, or ``detail_url`` field.
    """
    try:
        items = json.loads(json_content)
    except json.JSONDecodeError:
        print("  Failed to parse JSON content for link extraction")
        return []

    if not isinstance(items, list):
        items = [items]

    urls: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ("url", "href", "link", "detail_url"):
            val = item.get(key)
            if val and isinstance(val, str) and val.startswith("http"):
                urls.append(val)
                break
    return urls


async def _run_link_gathering_strategy(
    venue: dict, *, use_cache: bool = True, months: int | None = None
) -> list[Event]:
    """
    Link-gathering strategy:
    1. Crawl schedule page to discover event links.
    2. Crawl each event detail page.
    3. Combine all page contents into one document.
    4. Single LLM call for structured extraction.
    """
    venue_id = str(venue["_id"])
    venue_name = venue["name"]
    schedule_url_template = venue["schedule_url"]
    instructions = venue.get("scraping_instructions")
    schedule_css_selector = venue.get("schedule_css_selector")
    schedule_json_css_schema = venue.get("schedule_json_css_schema")
    detail_css_selector = venue.get("detail_css_selector")
    detail_json_css_schema = venue.get("detail_json_css_schema")
    content_type = venue.get("content_type", "fit_markdown")
    skip_llm_for_links = venue.get("skip_llm_for_links", False)
    detail_is_json = detail_json_css_schema is not None
    schedule_is_json = schedule_json_css_schema is not None

    templated = _url_is_templated(schedule_url_template)
    if months is None:
        months = DEFAULT_TEMPLATE_MONTHS if templated else 1

    all_events: list[Event] = []
    now = datetime.now()

    for offset in range(months):
        target = _add_months(now, offset)
        month_label = f"{target.year}-{target.month:02d}"
        print(f"[{venue_name}] --- Month {month_label} (offset {offset}) ---")

        schedule_url = resolve_schedule_url(schedule_url_template, target)
        cache_key_suffix = month_label if templated else None

        if offset == 0:
            print(f"[{venue_name}] Schedule URL: {schedule_url}")

        # Step 1: Crawl schedule page
        schedule_content = await crawl_schedule(
            venue_name,
            schedule_url,
            use_cache=use_cache,
            cache_key_suffix=cache_key_suffix,
            css_selector=schedule_css_selector,
            json_css_schema=schedule_json_css_schema,
            content_type=content_type,
        )

        # Step 2: Extract links
        if skip_llm_for_links:
            if schedule_is_json:
                detail_urls = _parse_links_from_json(schedule_content)
            else:
                # Attempt to pull hrefs from markdown via simple regex
                detail_urls = _extract_urls_from_markdown(schedule_content)
            print(f"  [{venue_name}] Parsed {len(detail_urls)} links directly (no LLM).")
        else:
            link_results = await extract_links(
                schedule_content, venue_name, instructions, is_json=schedule_is_json,
            )
            detail_urls = [lr["url"] for lr in link_results if lr.get("url")]
            print(f"  [{venue_name}] LLM extracted {len(detail_urls)} links.")

        if not detail_urls:
            print(f"  [{venue_name}] No event links found for {month_label}, skipping.")
            continue

        # Step 3: Crawl each event detail page
        detail_contents = await crawl_detail_pages(
            venue_name,
            detail_urls,
            use_cache=use_cache,
            css_selector=detail_css_selector,
            json_css_schema=detail_json_css_schema,
            content_type=content_type,
        )

        # Step 4: Combine into one document
        if detail_is_json:
            # Merge JSON arrays
            merged_items: list = []
            for dc in detail_contents:
                try:
                    items = json.loads(dc)
                    if isinstance(items, list):
                        merged_items.extend(items)
                    else:
                        merged_items.append(items)
                except json.JSONDecodeError:
                    pass
            combined = json.dumps(merged_items, ensure_ascii=False)
        else:
            parts = []
            for i, (url, content) in enumerate(zip(detail_urls, detail_contents), 1):
                parts.append(f"--- EVENT PAGE {i} ({url}) ---\n\n{content}")
            combined = "\n\n".join(parts)

        # Step 5: Single LLM call
        month_events = await extract_events_combined(
            combined,
            venue_id,
            venue_name,
            instructions,
            is_json=detail_is_json,
        )

        # Fill detail_url from the source URLs where missing
        url_set = set(detail_urls)
        for event in month_events:
            if not event.detail_url and len(detail_urls) == 1:
                event.detail_url = detail_urls[0]

        all_events.extend(month_events)
        print(f"[{venue_name}] Month {month_label}: {len(month_events)} events.")

    return all_events


def _extract_urls_from_markdown(markdown: str) -> list[str]:
    """Pull http(s) URLs from markdown link syntax ``[text](url)``."""
    import re

    pattern = re.compile(r"\[.*?\]\((https?://[^\s)]+)\)")
    return pattern.findall(markdown)


# ---------------------------------------------------------------------------
# Strategy: custom
# ---------------------------------------------------------------------------


async def _run_custom_strategy(venue: dict, *, use_cache: bool = True) -> list[Event]:
    """
    Custom strategy: load a script from scripts/ and call its ``run()`` function.

    The script must expose::

        async def run(venue: dict, **kwargs) -> list[Event]
    """
    venue_name = venue["name"]
    script_name = venue.get("custom_script")
    kwargs = venue.get("custom_kwargs") or {}

    if not script_name:
        print(f"[{venue_name}] No custom_script configured, skipping.")
        return []

    module_name = f"scripts.{script_name}"
    print(f"[{venue_name}] Running custom script: {module_name}")

    try:
        mod = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        print(f"[{venue_name}] Failed to import {module_name}: {e}")
        return []

    run_fn = getattr(mod, "run", None)
    if run_fn is None:
        print(f"[{venue_name}] Script {module_name} has no run() function.")
        return []

    try:
        events = await run_fn(venue, use_cache=use_cache, **kwargs)
    except Exception as e:
        print(f"[{venue_name}] Custom script error: {e}")
        import traceback

        traceback.print_exc()
        return []

    if not isinstance(events, list):
        print(f"[{venue_name}] Custom script must return list[Event], got {type(events)}")
        return []

    print(f"[{venue_name}] Custom script returned {len(events)} events.")
    return events


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


async def scrape_venue(
    venue: dict, *, use_cache: bool = True, months: int | None = None
) -> int:
    """
    Run the full scrape pipeline for a single venue.

    Dispatches to the appropriate strategy based on ``venue["scraping_strategy"]``.

    Returns the number of events saved.
    """
    venue_name = venue["name"]
    strategy = venue.get("scraping_strategy")

    if not strategy:
        print(f"[{venue_name}] No scraping_strategy configured, skipping.")
        return 0

    # Dispatch to the right strategy
    if strategy == ScrapingStrategy.SCHEDULE:
        events = await _run_schedule_strategy(venue, use_cache=use_cache, months=months)
    elif strategy == ScrapingStrategy.LINK_GATHERING:
        events = await _run_link_gathering_strategy(venue, use_cache=use_cache, months=months)
    elif strategy == ScrapingStrategy.CUSTOM:
        events = await _run_custom_strategy(venue, use_cache=use_cache)
    else:
        print(f"[{venue_name}] Unknown strategy: {strategy}")
        return 0

    if not events:
        print(f"[{venue_name}] No events extracted.")
        return 0

    saved = await _save_events(events)
    print(f"[{venue_name}] Saved {saved} events.")
    return saved


async def scrape_all(*, use_cache: bool = True, months: int | None = None) -> None:
    """Scrape all configured venues."""
    db = get_db()
    await init_db()

    venues = await db.venues.find(
        {
            "scraping_strategy": {"$ne": None},
            "$or": [
                {"venue_state": {"$in": [VenueState.CONFIGURED.value, VenueState.WARNING.value]}},
                {"venue_state": {"$exists": False}},
            ],
        }
    ).to_list(100)

    if not venues:
        print("No venues with scraping_strategy configured and state configured/warning.")
        print("Run venue_loader first, then configure venues.")
        return

    print(f"Found {len(venues)} configured venues.\n")

    total = 0
    for venue in venues:
        try:
            count = await scrape_venue(venue, use_cache=use_cache, months=months)
            total += count
        except Exception as e:
            print(f"[{venue['name']}] ERROR: {e}")

    print(f"\n{'=' * 60}")
    print(f"Done. Total events saved: {total}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_main_args() -> tuple[bool, str | None, int | None]:
    """Return (no_cache, venue_filter, months)."""
    no_cache = "--no-cache" in sys.argv
    venue_filter = None
    months: int | None = None
    positionals: list[str] = []

    i = 1
    while i < len(sys.argv):
        a = sys.argv[i]
        if a == "--no-cache":
            i += 1
            continue
        if a == "--months":
            if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
                months = max(1, int(sys.argv[i + 1]))
                i += 2
                continue
            i += 1
            continue
        if a.startswith("--months="):
            try:
                months = max(1, int(a.split("=", 1)[1]))
            except ValueError:
                pass
            i += 1
            continue
        if not a.startswith("--"):
            positionals.append(a)
        i += 1

    if positionals:
        venue_filter = positionals[0]
    return no_cache, venue_filter, months


async def main() -> None:
    """CLI entry point."""
    no_cache, venue_filter, months = _parse_main_args()

    db = get_db()
    await init_db()

    if venue_filter:
        venue = await db.venues.find_one(
            {"name": {"$regex": venue_filter, "$options": "i"}}
        )
        if not venue:
            print(f"No venue found matching: {venue_filter}")
            await close_db()
            return
        await scrape_venue(venue, use_cache=not no_cache, months=months)
    else:
        await scrape_all(use_cache=not no_cache, months=months)

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
