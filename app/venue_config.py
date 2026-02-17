"""CLI to list venues and update their scraping config."""

import asyncio
import json
import sys
from datetime import datetime, timezone

from app.db import close_db, get_db
from app.models import ScrapingStrategy
from app.pipeline import resolve_schedule_url


async def list_venues() -> None:
    """Print all venues with their current config."""
    db = get_db()
    venues = await db.venues.find().to_list(100)

    if not venues:
        print("No venues found. Run venue_loader first.")
        return

    now = datetime.now()
    for i, v in enumerate(venues, 1):
        strategy = v.get("scraping_strategy") or "not set"
        schedule = v.get("schedule_url") or "not set"
        instructions = v.get("scraping_instructions") or "not set"
        default_img = v.get("default_image_url") or "not set"
        sched_css = v.get("schedule_css_selector") or "not set"
        detail_css = v.get("detail_css_selector") or "not set"
        sched_json = v.get("schedule_json_css_schema")
        detail_json = v.get("detail_json_css_schema")
        skip_llm = v.get("skip_llm_for_links", False)
        custom_script = v.get("custom_script") or "not set"
        custom_kwargs = v.get("custom_kwargs")

        print(f"  {i}. {v['name']} (id: {v['_id']})")
        print(f"     Schedule URL:     {schedule}")
        if v.get("schedule_url") and "{" in v["schedule_url"]:
            resolved = resolve_schedule_url(v["schedule_url"], now)
            print(f"       -> this month:  {resolved}")
        print(f"     Strategy:         {strategy}")
        print(f"     Instructions:     {instructions}")
        print(f"     Default image:    {default_img}")
        if sched_css != "not set":
            print(f"     Schedule CSS:     {sched_css}")
        if detail_css != "not set":
            print(f"     Detail CSS:       {detail_css}")
        if sched_json:
            print(f"     Schedule JSON schema: (set)")
        if detail_json:
            print(f"     Detail JSON schema:   (set)")
        if skip_llm:
            print(f"     Skip LLM for links: {skip_llm}")
        if custom_script != "not set":
            print(f"     Custom script:    {custom_script}")
        if custom_kwargs:
            print(f"     Custom kwargs:    {json.dumps(custom_kwargs, ensure_ascii=False)}")
        print()


async def configure_venue(venue_id: str) -> None:
    """Interactively configure a venue's scraping fields."""
    from bson import ObjectId

    db = get_db()
    venue = await db.venues.find_one({"_id": ObjectId(venue_id)})

    if not venue:
        print(f"Venue not found: {venue_id}")
        return

    print(f"Configuring: {venue['name']}\n")

    # Schedule URL (template)
    current = venue.get("schedule_url") or ""
    print("  Use {year} and {month} placeholders for monthly URLs.")
    print("  Examples: .../schedule/{year}/{month:02d}  or  .../{year}schedule_{month}.html")
    print("  Leave placeholders out if the URL is static (always shows current month).")
    url = input(f"  Schedule URL [{current}]: ").strip()
    if not url:
        url = current

    # Strategy
    current_strat = venue.get("scraping_strategy") or ""
    strategies = ", ".join(s.value for s in ScrapingStrategy)
    print(f"  Strategy options: {strategies}")
    strat = input(f"  Strategy [{current_strat}]: ").strip()
    if not strat:
        strat = current_strat

    # Instructions
    current_instr = venue.get("scraping_instructions") or ""
    instr = input(f"  Extra instructions [{current_instr}]: ").strip()
    if not instr:
        instr = current_instr

    # Default image
    current_img = venue.get("default_image_url") or ""
    img = input(f"  Default image URL [{current_img}]: ").strip()
    if not img:
        img = current_img

    # CSS selectors
    print("  CSS selectors narrow the page content before LLM extraction.")
    print("  Examples: #schedule-list, .event-container, article.main-content")
    current_sched_css = venue.get("schedule_css_selector") or ""
    sched_css = input(f"  Schedule page CSS selector [{current_sched_css}]: ").strip()
    if not sched_css:
        sched_css = current_sched_css

    current_detail_css = venue.get("detail_css_selector") or ""
    detail_css = input(f"  Detail page CSS selector [{current_detail_css}]: ").strip()
    if not detail_css:
        detail_css = current_detail_css

    # Link-gathering specific: skip_llm_for_links
    current_skip = venue.get("skip_llm_for_links", False)
    skip_input = input(f"  Skip LLM for link gathering (true/false) [{current_skip}]: ").strip().lower()
    skip_llm = skip_input == "true" if skip_input else current_skip

    # Custom script
    current_script = venue.get("custom_script") or ""
    script = input(f"  Custom script name (for custom strategy) [{current_script}]: ").strip()
    if not script:
        script = current_script

    update = {
        "schedule_url": url or None,
        "scraping_strategy": strat or None,
        "scraping_instructions": instr or None,
        "default_image_url": img or None,
        "schedule_css_selector": sched_css or None,
        "detail_css_selector": detail_css or None,
        "skip_llm_for_links": skip_llm,
        "custom_script": script or None,
        "updated_at": datetime.now(timezone.utc),
    }

    await db.venues.update_one({"_id": ObjectId(venue_id)}, {"$set": update})
    print(f"\nUpdated {venue['name']}.")


async def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] == "list":
        await list_venues()
    elif args[0] == "configure" and len(args) == 2:
        await configure_venue(args[1])
    else:
        print("Usage:")
        print("  uv run -m app.venue_config list")
        print("  uv run -m app.venue_config configure <venue_id>")

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
