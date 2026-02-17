from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ScrapingStrategy(str, Enum):
    SCHEDULE = "schedule"
    LINK_GATHERING = "link_gathering"
    CUSTOM = "custom"


class GeoLocation(BaseModel):
    """GeoJSON Point for MongoDB 2dsphere index."""

    type: str = "Point"
    coordinates: list[float] = Field(
        ..., description="[longitude, latitude]", min_length=2, max_length=2
    )


class Venue(BaseModel):
    """A live-house venue."""

    name: str
    google_place_id: Optional[str] = None
    location: Optional[GeoLocation] = None
    address: Optional[str] = None
    website: Optional[str] = None
    google_maps_url: Optional[str] = None
    rating: Optional[float] = None

    # Default image for events without a flyer
    default_image_url: Optional[str] = Field(
        None, description="Fallback image URL for events at this venue"
    )

    # Scraping config
    schedule_url: Optional[str] = Field(
        None,
        description="URL or URL template for the schedule page. "
        "Supports {year}, {month}, {month:02d} placeholders.",
    )
    scraping_strategy: Optional[ScrapingStrategy] = None
    scraping_instructions: Optional[str] = None

    # CSS selectors to narrow crawled content before LLM extraction
    schedule_css_selector: Optional[str] = Field(
        None,
        description="CSS selector to scope schedule page content.",
    )
    detail_css_selector: Optional[str] = Field(
        None,
        description="CSS selector to scope detail/event page content (link_gathering only).",
    )

    # JsonCssExtractionStrategy schemas (alternative to css selectors)
    schedule_json_css_schema: Optional[dict[str, Any]] = Field(
        None,
        description="Crawl4AI JsonCssExtractionStrategy schema for the schedule page. "
        "When set, crawl returns JSON instead of markdown.",
    )
    detail_json_css_schema: Optional[dict[str, Any]] = Field(
        None,
        description="JsonCssExtractionStrategy schema for event detail pages (link_gathering only).",
    )

    # Link-gathering strategy options
    skip_llm_for_links: bool = Field(
        False,
        description="When True, event links are parsed directly from CSS/JSON extraction output "
        "instead of using LLM to identify them.",
    )

    # Custom strategy options
    custom_script: Optional[str] = Field(
        None,
        description="Script module name in scripts/ directory (without .py extension).",
    )
    custom_kwargs: Optional[dict[str, Any]] = Field(
        None,
        description="JSON kwargs passed to the custom script's run() function.",
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Event(BaseModel):
    """An event at a venue."""

    venue_id: str
    title: str
    date: str = Field(..., description="ISO date string YYYY-MM-DD")
    time_open: Optional[str] = None
    time_start: Optional[str] = None
    price: Optional[int] = Field(None, description="Price in yen (advance)")
    price_text: Optional[str] = Field(
        None, description="Original price text, e.g. '前売 3500円 / 当日 4000円'"
    )
    artists: list[str] = Field(default_factory=list)
    image_url: Optional[str] = Field(
        None, description="URL of the main event image/flyer"
    )
    detail_url: Optional[str] = None
    raw_text: Optional[str] = Field(
        None, description="Original scraped text for debugging"
    )
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
