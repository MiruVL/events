"""Extract structured event data from crawled content using a local LLM via LM Studio."""

import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from typing import Literal, Optional

import httpx

from app.config import settings
from app.models import Event

PageType = Literal["schedule", "detail"]

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_SCHEDULE = """You are a data extraction assistant. You extract live music event information from Japanese live-house schedule pages.

Given the content of a schedule page (markdown or structured JSON), extract ALL events into a JSON array — but ONLY from the main schedule section.

Main schedule section: the primary list or calendar that contains the most events and the most detail (dates, times, titles, links to detail pages). It is usually the central content, often under a heading like "SCHEDULE", "スケジュール", or the month name.

IGNORE and do NOT extract from:
- "Featured events", "ピックアップ", "おすすめ", "Recommended", "関連イベント"
- Sidebars or boxes that repeat or highlight a few events
- Ads, banners, or "other venues" sections
- Any block that looks like a summary or teaser rather than the main schedule list

For each event from the main schedule only, extract:
- "title": event/show name (string)
- "date": date in YYYY-MM-DD format (string)
- "time_open": door open time in HH:MM format or null
- "time_start": show start time in HH:MM format or null
- "price": advance ticket price in yen as integer, or null if not found
- "price_text": original price text as written on the page (string or null)
- "artists": array of performer/artist names (array of strings, can be empty)
- "image_url": URL of the main event image or flyer (string or null). Look for img tags near the event info.
- "detail_url": link to event detail page if present (string or null)

Rules:
- Dates: Convert Japanese date formats (e.g. 2月15日(土)) to YYYY-MM-DD. Use the current year if not specified.
- Prices: Extract the advance/pre-sale price (前売) as the integer. Keep the full text in price_text.
- Artists: List each performer separately. Split on common separators (/, ・, and, etc.)
- If a field is not found, use null (not empty string).
- Output ONLY the JSON array. No explanation, no markdown fences."""

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
- "title": event/show name (string)
- "date": date in YYYY-MM-DD format (string)
- "time_open": door open time in HH:MM format or null
- "time_start": show start time in HH:MM format or null
- "price": advance ticket price in yen as integer, or null if not found
- "price_text": original price text as written on the page (string or null)
- "artists": array of performer/artist names (array of strings, can be empty)
- "image_url": URL of the main event image or flyer (string or null)
- "detail_url": this page's URL if you have it, or null

Rules:
- Output a JSON array with one or more events. No explanation, no markdown fences.
- Prefer the most detailed, central content; ignore featured/related sections and ads."""

SYSTEM_PROMPT_LINKS = """You are a data extraction assistant. You extract event detail page links from a live-house schedule page.

Given the markdown content of a schedule page, find ALL links that point to individual event detail pages.

For each link, return a JSON object with:
- "url": the full URL of the event detail page (string)
- "title": the event title associated with this link, if visible (string or null)
- "date": the event date in YYYY-MM-DD format, if visible (string or null)

Rules:
- Only include links to event detail pages (individual show/event pages).
- Do NOT include links to other months, archives, ticket purchase, social media, or external sites.
- Convert relative URLs to absolute if you can determine the base URL from context.
- Output ONLY a JSON array. No explanation, no markdown fences."""

SYSTEM_PROMPT_COMBINED = """You are a data extraction assistant. You extract live music event information from combined content of multiple event detail pages from a Japanese live-house venue.

The content below contains multiple event pages concatenated together, each separated by a marker. Extract ALL events into a single JSON array.

For each event, extract:
- "title": event/show name (string)
- "date": date in YYYY-MM-DD format (string)
- "time_open": door open time in HH:MM format or null
- "time_start": show start time in HH:MM format or null
- "price": advance ticket price in yen as integer, or null if not found
- "price_text": original price text as written on the page (string or null)
- "artists": array of performer/artist names (array of strings, can be empty)
- "image_url": URL of the main event image or flyer (string or null)
- "detail_url": the URL of the page this event came from (string or null)

Rules:
- Dates: Convert Japanese date formats (e.g. 2月15日(土)) to YYYY-MM-DD. Use the current year if not specified.
- Prices: Extract the advance/pre-sale price (前売) as the integer. Keep the full text in price_text.
- Artists: List each performer separately. Split on common separators (/, ・, and, etc.)
- If a field is not found, use null (not empty string).
- Output ONLY the JSON array. No explanation, no markdown fences."""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trim_markdown(markdown: str) -> str:
    """Strip navigation, headers, and footers — keep only the schedule content."""
    lines = markdown.split("\n")
    start = 0
    end = len(lines)

    start_markers = ["**0", "* * *"]
    schedule_heading = re.compile(r"^##\s*SCHEDULE\s*$", re.IGNORECASE)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if schedule_heading.match(stripped):
            start = i
            break
        if any(stripped.startswith(m) for m in start_markers):
            start = i
            break
        if stripped == "---":
            start = i
            break

    footer_markers = ["PAGETOP", "Copyright", "copyright", "©"]
    for i in range(len(lines) - 1, start, -1):
        if any(m in lines[i] for m in footer_markers):
            end = i
            break

    trimmed = "\n".join(lines[start:end])
    return trimmed


async def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """Send a chat completion request to the LLM and return the raw text response."""
    url = f"{settings.llm_base_url}/chat/completions"
    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "stream": True,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    print(f"  Sending to {settings.llm_model} ({len(user_prompt)} chars prompt)...")

    raw_content = ""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=30, read=120, write=30, pool=30)
    ) as client:
        try:
            async with client.stream("POST", url, json=payload) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    print(f"  LLM API error {resp.status_code}: {body.decode()}")
                    resp.raise_for_status()
                token_count = 0
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:]
                    if chunk.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                        choices = data.get("choices")
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            raw_content += text
                            token_count += 1
                            if token_count % 100 == 0:
                                print(f"  ... {token_count} tokens received", end="\r")
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
        except httpx.HTTPError as e:
            print(f"  Connection error: {e}")
            raise

    # Strip Qwen3 thinking tags if present
    if "<think>" in raw_content:
        raw_content = raw_content.split("</think>")[-1].strip()

    print(f"  LLM response: {len(raw_content)} chars, ~{token_count} tokens")
    return raw_content


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
    if not is_json:
        content = _trim_markdown(content)

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

    prompt += "\n\n/no_think"
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

    prompt += "\n\n/no_think"
    return prompt


def _build_link_extraction_prompt(
    content: str,
    venue_name: str,
    extra_instructions: Optional[str] = None,
    is_json: bool = False,
) -> str:
    """Build the user prompt for link extraction from a schedule page."""
    if not is_json:
        content = _trim_markdown(content)

    prompt = f"Extract all event detail page links from the schedule for venue: {venue_name}\n\n"

    if extra_instructions:
        prompt += f"Additional instructions: {extra_instructions}\n\n"

    if is_json:
        prompt += f"Structured data extracted from the schedule page (JSON):\n\n{content}"
    else:
        prompt += f"Schedule page content:\n\n{content}"

    prompt += "\n\n/no_think"
    return prompt


def _system_prompt_for(page_type: PageType) -> str:
    return SYSTEM_PROMPT_SCHEDULE if page_type == "schedule" else SYSTEM_PROMPT_DETAIL


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def _repair_json(text: str) -> str:
    """Attempt to fix common LLM JSON issues."""
    text = re.sub(r",\s*([}\]])", r"\1", text)
    open_brackets = text.count("[") - text.count("]")
    open_braces = text.count("{") - text.count("}")
    text = text.rstrip().rstrip(",")
    text += "}" * max(0, open_braces)
    text += "]" * max(0, open_brackets)
    return text


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences the LLM may have added."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text


def _parse_json_response(raw: str) -> list | dict | None:
    """Parse a JSON response from the LLM, with repair fallback."""
    text = _strip_markdown_fences(raw)

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  JSON parse failed ({e}), attempting repair...")
        repaired = _repair_json(text)
        try:
            result = json.loads(repaired)
            print("  JSON repair succeeded.")
            return result
        except json.JSONDecodeError:
            print("  JSON repair failed, trying partial extraction...")
            partial = _extract_partial_json(text)
            if partial is not None:
                return partial
            debug_path = "crawl_cache/_last_failed_llm_response.txt"
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(raw)
            print(f"  Saved raw LLM response to {debug_path}")
            return None


def _parse_llm_response_as_events(raw: str, venue_id: str) -> list[Event]:
    """Parse and validate LLM JSON response into Event objects."""
    parsed = _parse_json_response(raw)
    if parsed is None:
        raise ValueError("Could not parse LLM response as JSON")

    if isinstance(parsed, dict):
        for key in ("events", "data", "results"):
            if key in parsed:
                parsed = parsed[key]
                break
        else:
            parsed = [parsed]

    if not isinstance(parsed, list):
        raise ValueError(f"Expected a JSON array, got: {type(parsed)}")

    events = []
    now = datetime.now(timezone.utc)
    for item in parsed:
        try:
            event = Event(
                venue_id=venue_id,
                title=item.get("title", "Unknown"),
                date=item.get("date", ""),
                time_open=item.get("time_open"),
                time_start=item.get("time_start"),
                price=item.get("price"),
                price_text=item.get("price_text"),
                artists=item.get("artists", []),
                image_url=item.get("image_url"),
                detail_url=item.get("detail_url"),
                raw_text=json.dumps(item, ensure_ascii=False),
                scraped_at=now,
            )
            events.append(event)
        except Exception as e:
            print(f"  Warning: skipped invalid event: {e}")
            continue

    return events


def _extract_partial_json(text: str) -> list | None:
    """Try to extract individual JSON objects from a broken array."""
    results = []
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                fragment = text[start : i + 1]
                try:
                    obj = json.loads(fragment)
                    if isinstance(obj, dict) and "title" in obj:
                        results.append(obj)
                except json.JSONDecodeError:
                    pass
                start = None
    if results:
        print(f"  Partial extraction recovered {len(results)} events.")
        return results
    return None


# ---------------------------------------------------------------------------
# Public extraction functions
# ---------------------------------------------------------------------------


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
        content: Page content — markdown string or JSON string (when
            JsonCssExtractionStrategy was used).
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

    raw = await _call_llm(system_content, user_prompt)
    events = _parse_llm_response_as_events(raw, venue_id)
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

    raw = await _call_llm(SYSTEM_PROMPT_COMBINED, user_prompt)
    events = _parse_llm_response_as_events(raw, venue_id)
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
        content: Schedule page content (markdown or JSON).
        venue_name: Name of the venue.
        extra_instructions: Optional per-venue scraping notes.
        is_json: True when content is JSON from JsonCssExtractionStrategy.

    Returns:
        List of dicts with at least "url" key, and optional "title" / "date".
    """
    user_prompt = _build_link_extraction_prompt(
        content, venue_name, extra_instructions, is_json=is_json
    )

    raw = await _call_llm(SYSTEM_PROMPT_LINKS, user_prompt)
    parsed = _parse_json_response(raw)

    if parsed is None:
        print("  Failed to parse link extraction response")
        return []

    if isinstance(parsed, dict):
        for key in ("links", "urls", "data", "results"):
            if key in parsed:
                parsed = parsed[key]
                break
        else:
            parsed = [parsed]

    if not isinstance(parsed, list):
        print(f"  Expected a JSON array of links, got: {type(parsed)}")
        return []

    links = [item for item in parsed if isinstance(item, dict) and item.get("url")]
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
