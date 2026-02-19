"""Extract structured event data from crawled content using a local LLM."""

import asyncio
import sys
from datetime import datetime, timezone
from typing import Literal, Optional, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import settings
from app.models import Event

PageType = Literal["schedule", "detail"]

# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------

_llm_client = AsyncOpenAI(
    base_url=settings.llm_base_url,
    api_key="lm-studio",
    timeout=120.0,
)

# ---------------------------------------------------------------------------
# LLM response schemas
# ---------------------------------------------------------------------------


class LLMEvent(BaseModel):
    title: str
    date: str
    time_open: Optional[str] = None
    time_start: Optional[str] = None
    price: Optional[int] = None
    price_text: Optional[str] = None
    artists: list[str] = []
    image_url: Optional[str] = None
    detail_url: Optional[str] = None


class EventExtractionResponse(BaseModel):
    events: list[LLMEvent]


class LLMLink(BaseModel):
    url: str
    title: Optional[str] = None
    date: Optional[str] = None


class LinkExtractionResponse(BaseModel):
    links: list[LLMLink]


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_SCHEDULE = """You are a data extraction assistant. You extract live music event information from Japanese live-house schedule pages.

Given the content of a schedule page (markdown or structured JSON), extract ALL events — but ONLY from the main schedule section.

Main schedule section: the primary list or calendar that contains the most events and the most detail (dates, times, titles, links to detail pages). It is usually the central content, often under a heading like "SCHEDULE", "スケジュール", or the month name.

IGNORE and do NOT extract from:
- "Featured events", "ピックアップ", "おすすめ", "Recommended", "関連イベント"
- Sidebars or boxes that repeat or highlight a few events
- Ads, banners, or "other venues" sections
- Any block that looks like a summary or teaser rather than the main schedule list
- Events that does not look like an event (e.g, hall rentals, etc.)

For each event from the main schedule only, extract:
- "title": event/show name
- "date": date in YYYY-MM-DD format
- "time_open": door open time in HH:MM format or null
- "time_start": show start time in HH:MM format or null
- "price": advance ticket price in yen as integer, or null if not found
- "price_text": original price text as written on the page, or null
- "artists": array of performer/artist names (can be empty)
- "image_url": URL of the main event image or flyer, or null. Look for img tags near the event info. If event has more than one image, use the first one.
- "detail_url": link to event detail page if present, or null

Rules:
- Dates: Convert Japanese date formats (e.g. 2月15日(土)) to YYYY-MM-DD. Use the current year if not specified.
- Prices: Extract the advance/pre-sale price (前売) as the integer. Keep the full text in price_text.
- Artists: List each performer separately. Split on common separators (/, ・, and, etc.)
- If a field is not found, use null (not empty string)."""

SYSTEM_PROMPT_DETAIL = """You are a data extraction assistant. You extract live music events from an event detail page or a day page.

The page may be:
- A single event detail page: extract that one event (the main subject of the page).
- A day page listing multiple events on the same day: extract ALL events from the main content.

Extract only events that are the main content of this page (most detail: title, date, times, price, artists, image). If you are given an expected title and/or date, the page is likely about that event (or that day); include events that match.

IGNORE and do NOT extract as separate events:
- "Featured events", "他のイベント", "Related", "おすすめ", "ピックアップ"
- Sidebar or footer event lists, "next events", ads
- Teaser/summary blocks that repeat events from elsewhere

For each event, extract:
- "title": event/show name
- "date": date in YYYY-MM-DD format
- "time_open": door open time in HH:MM format or null
- "time_start": show start time in HH:MM format or null
- "price": advance ticket price in yen as integer, or null if not found
- "price_text": original price text as written on the page, or null
- "artists": array of performer/artist names (can be empty)
- "image_url": URL of the main event image or flyer, or null
- "detail_url": this page's URL if you have it, or null

Rules:
- Prefer the most detailed, central content; ignore featured/related sections and ads."""

SYSTEM_PROMPT_LINKS = """You are a data extraction assistant. You extract event detail page links from a live-house schedule page.

Given the markdown content of a schedule page, find ALL links that point to individual event detail pages.

For each link, extract:
- "url": the full URL of the event detail page
- "title": the event title associated with this link, if visible, or null
- "date": the event date in YYYY-MM-DD format, if visible, or null

Rules:
- Only include links to event detail pages (individual show/event pages).
- Do NOT include links to other months, archives, ticket purchase, social media, or external sites.
- Convert relative URLs to absolute if you can determine the base URL from context."""

SYSTEM_PROMPT_COMBINED = """You are a data extraction assistant. You extract live music event information from combined content of multiple event detail pages from a Japanese live-house venue.

The content below contains multiple event pages concatenated together, each separated by a marker. Extract ALL events.
Ignore and do not extract events that does not look like an event (e.g, hall rentals, etc.)

For each event, extract:
- "title": event/show name
- "date": date in YYYY-MM-DD format
- "time_open": door open time in HH:MM format or null
- "time_start": show start time in HH:MM format or null
- "price": advance ticket price in yen as integer, or null if not found
- "price_text": original price text as written on the page, or null
- "artists": array of performer/artist names (can be empty)
- "image_url": URL of the main event image or flyer, or null
- "detail_url": the URL of the page this event came from, or null

Rules:
- Dates: Convert Japanese date formats (e.g. 2月15日(土)) to YYYY-MM-DD. Use the current year if not specified.
- Prices: Extract the advance/pre-sale price (前売) as the integer. Keep the full text in price_text.
- Artists: List each performer separately. Split on common separators (/, ・, and, etc.)
- If a field is not found, use null (not empty string)."""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T = TypeVar("_T", bound=BaseModel)


async def _call_llm_structured(
    system_prompt: str,
    user_prompt: str,
    response_model: type[_T],
) -> _T:
    """Send a chat completion with structured output and return the parsed model."""
    print(f"  Sending to {settings.llm_model} ({len(user_prompt)} chars prompt)...")

    completion = await _llm_client.beta.chat.completions.parse(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format=response_model,
        temperature=0.1,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )

    result = completion.choices[0].message

    if result.refusal:
        raise ValueError(f"LLM refused the request: {result.refusal}")
    if result.parsed is None:
        raise ValueError(f"Failed to parse LLM response: {result.content}")

    print(f"  LLM response parsed successfully ({len(result.content or '')} chars)")
    return result.parsed


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def _build_event_extraction_prompt(
    content: str,
    venue_name: str,
    extra_instructions: Optional[str] = None,
    page_type: PageType = "schedule",
    expected_title: Optional[str] = None,
    expected_date: Optional[str] = None,
    is_json: bool = False,
) -> str:
    """Build the user prompt for event extraction."""

    if page_type == "schedule":
        prompt = f"Extract all events from the main schedule section only (ignore featured/pickup/ads) for venue: {venue_name}\n\n"
    else:
        prompt = f"Extract the main event(s) from this detail or day page for venue: {venue_name}.\n\n"
        if expected_title or expected_date:
            parts = []
            if expected_title:
                parts.append(f"Expected event title (match this): {expected_title}")
            if expected_date:
                parts.append(f"Expected date: {expected_date}")
            prompt += " ".join(parts) + "\n\n"

    if extra_instructions:
        prompt += f"Additional instructions: {extra_instructions}\n\n"

    if is_json:
        prompt += f"Structured data extracted from the page (JSON):\n\n{content}"
    else:
        prompt += f"Page content:\n\n{content}"

    return prompt


def _build_combined_extraction_prompt(
    combined_content: str,
    venue_name: str,
    extra_instructions: Optional[str] = None,
    is_json: bool = False,
) -> str:
    """Build prompt for extracting events from combined multi-page content."""
    prompt = f"Extract all events from these combined event pages for venue: {venue_name}\n\n"

    if extra_instructions:
        prompt += f"Additional instructions: {extra_instructions}\n\n"

    if is_json:
        prompt += f"Structured data extracted from the pages (JSON):\n\n{combined_content}"
    else:
        prompt += f"Combined page content:\n\n{combined_content}"

    return prompt


def _build_link_extraction_prompt(
    content: str,
    venue_name: str,
    extra_instructions: Optional[str] = None,
    is_json: bool = False,
) -> str:
    """Build the user prompt for link extraction from a schedule page."""
    prompt = f"Extract all event detail page links from the schedule for venue: {venue_name}\n\n"

    if extra_instructions:
        prompt += f"Additional instructions: {extra_instructions}\n\n"

    if is_json:
        prompt += f"Structured data extracted from the schedule page (JSON):\n\n{content}"
    else:
        prompt += f"Schedule page content:\n\n{content}"

    return prompt


def _system_prompt_for(page_type: PageType) -> str:
    return SYSTEM_PROMPT_SCHEDULE if page_type == "schedule" else SYSTEM_PROMPT_DETAIL


# ---------------------------------------------------------------------------
# Public extraction functions
# ---------------------------------------------------------------------------


def _llm_events_to_events(llm_events: list[LLMEvent], venue_id: str) -> list[Event]:
    """Convert LLM response events to Event model instances."""
    now = datetime.now(timezone.utc)
    events = []
    for e in llm_events:
        try:
            events.append(
                Event(
                    venue_id=venue_id,
                    raw_text=e.model_dump_json(),
                    scraped_at=now,
                    **e.model_dump(),
                )
            )
        except Exception as exc:
            print(f"  Warning: skipped invalid event: {exc}")
    return events


async def extract_events(
    content: str,
    venue_id: str,
    venue_name: str,
    extra_instructions: Optional[str] = None,
    page_type: PageType = "schedule",
    expected_title: Optional[str] = None,
    expected_date: Optional[str] = None,
    is_json: bool = False,
) -> list[Event]:
    """
    Send page content to LLM and parse structured event data.

    Args:
        content: Page content — markdown, HTML, or JSON string.
        venue_id: MongoDB ObjectId of the venue (as string).
        venue_name: Name of the venue (for the prompt).
        extra_instructions: Optional per-venue scraping notes.
        page_type: "schedule" or "detail".
        expected_title: For detail pages, the expected event title.
        expected_date: For detail pages, the expected event date.
        is_json: True when content is JSON from JsonCssExtractionStrategy.

    Returns:
        List of validated Event objects.
    """
    user_prompt = _build_event_extraction_prompt(
        content,
        venue_name,
        extra_instructions,
        page_type=page_type,
        expected_title=expected_title,
        expected_date=expected_date,
        is_json=is_json,
    )
    system_content = _system_prompt_for(page_type)

    response = await _call_llm_structured(
        system_content, user_prompt, EventExtractionResponse
    )
    events = _llm_events_to_events(response.events, venue_id)
    print(f"  Extracted {len(events)} events")
    return events


async def extract_events_combined(
    combined_content: str,
    venue_id: str,
    venue_name: str,
    extra_instructions: Optional[str] = None,
    is_json: bool = False,
) -> list[Event]:
    """
    Extract events from combined multi-page content in a single LLM call.

    Used by the link_gathering strategy: after crawling all event detail pages,
    their content is concatenated and sent to the LLM as one document.

    Args:
        combined_content: Concatenated page contents separated by markers.
        venue_id: MongoDB ObjectId of the venue (as string).
        venue_name: Name of the venue.
        extra_instructions: Optional per-venue scraping notes.
        is_json: True when content is JSON from JsonCssExtractionStrategy.

    Returns:
        List of validated Event objects.
    """
    user_prompt = _build_combined_extraction_prompt(
        combined_content, venue_name, extra_instructions, is_json=is_json
    )

    response = await _call_llm_structured(
        SYSTEM_PROMPT_COMBINED, user_prompt, EventExtractionResponse
    )
    events = _llm_events_to_events(response.events, venue_id)
    print(f"  Extracted {len(events)} events from combined content")
    return events


async def extract_links(
    content: str,
    venue_name: str,
    extra_instructions: Optional[str] = None,
    is_json: bool = False,
) -> list[dict]:
    """
    Extract event detail page links from a schedule page via LLM.

    Args:
        content: Schedule page content (markdown, HTML, or JSON).
        venue_name: Name of the venue.
        extra_instructions: Optional per-venue scraping notes.
        is_json: True when content is JSON from JsonCssExtractionStrategy.

    Returns:
        List of dicts with at least "url" key, and optional "title" / "date".
    """
    user_prompt = _build_link_extraction_prompt(
        content, venue_name, extra_instructions, is_json=is_json,
    )

    response = await _call_llm_structured(
        SYSTEM_PROMPT_LINKS, user_prompt, LinkExtractionResponse
    )
    links = [link.model_dump() for link in response.links]
    print(f"  Extracted {len(links)} event links")
    return links


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


async def main() -> None:
    """CLI: extract events from a cached crawl file."""
    if len(sys.argv) < 3:
        print("Usage: uv run -m app.extractor <crawl_cache_file> <venue_name>")
        print('Example: uv run -m app.extractor crawl_cache/example.md "Club Quattro"')
        sys.exit(1)

    from pathlib import Path

    cache_file = Path(sys.argv[1])
    venue_name = sys.argv[2]

    if not cache_file.exists():
        print(f"File not found: {cache_file}")
        sys.exit(1)

    content = cache_file.read_text(encoding="utf-8")
    is_json = cache_file.suffix == ".json"

    events = await extract_events(
        content, venue_id="test", venue_name=venue_name, is_json=is_json
    )

    print(f"\n{'=' * 60}")
    print(f"EXTRACTED {len(events)} EVENTS")
    print(f"{'=' * 60}")
    for e in events:
        print(f"  {e.date} | {e.title}")
        if e.artists:
            print(f"           Artists: {', '.join(e.artists)}")
        if e.price_text:
            print(f"           Price: {e.price_text}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
