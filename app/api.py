"""FastAPI backend for serving venues and events."""

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from bson import ObjectId
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import close_db, get_db, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(title="Live-house Events API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _serialize_doc(doc: dict) -> dict:
    """Convert MongoDB document to JSON-safe dict."""
    doc["id"] = str(doc.pop("_id"))
    return doc


# ── Venues ──────────────────────────────────────────────────


@app.get("/venues")
async def list_venues(
    lat: Optional[float] = Query(None, description="Latitude for geo filter"),
    lng: Optional[float] = Query(None, description="Longitude for geo filter"),
    radius_km: float = Query(10, description="Radius in km for geo filter"),
):
    """List venues that are configured or in warning state (excludes new/disabled)."""
    db = get_db()

    query: dict = {
        "$or": [
            {"venue_state": {"$in": ["configured", "warning"]}},
            {"venue_state": {"$exists": False}},  # backwards compat: no field = show
        ]
    }

    if lat is not None and lng is not None:
        query["location"] = {
            "$nearSphere": {
                "$geometry": {
                    "type": "Point",
                    "coordinates": [lng, lat],
                },
                "$maxDistance": radius_km * 1000,
            }
        }

    venues = await db.venues.find(query).to_list(200)
    return [_serialize_doc(v) for v in venues]


@app.get("/venues/{venue_id}")
async def get_venue(venue_id: str):
    """Get a single venue by ID."""
    db = get_db()
    venue = await db.venues.find_one({"_id": ObjectId(venue_id)})
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")
    return _serialize_doc(venue)


# ── Events ──────────────────────────────────────────────────


@app.get("/events")
async def list_events(
    venue_id: Optional[str] = Query(None, description="Filter by venue ID"),
    date_from: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    price_min: Optional[int] = Query(None, description="Min price in yen"),
    price_max: Optional[int] = Query(None, description="Max price in yen"),
    search: Optional[str] = Query(None, description="Text search in title/artists"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List events with filters."""
    db = get_db()
    query: dict = {}

    if venue_id:
        query["venue_id"] = venue_id

    if date_from or date_to:
        date_filter = {}
        if date_from:
            date_filter["$gte"] = date_from
        if date_to:
            date_filter["$lte"] = date_to
        query["date"] = date_filter

    if price_min is not None or price_max is not None:
        price_filter = {}
        if price_min is not None:
            price_filter["$gte"] = price_min
        if price_max is not None:
            price_filter["$lte"] = price_max
        query["price"] = price_filter

    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"artists": {"$regex": search, "$options": "i"}},
        ]

    cursor = db.events.find(query).sort("date", 1).skip(offset).limit(limit)
    events = await cursor.to_list(limit)

    # Attach venue names
    venue_ids = list({e["venue_id"] for e in events})
    venues_map = {}
    if venue_ids:
        venue_object_ids = []
        for vid in venue_ids:
            try:
                venue_object_ids.append(ObjectId(vid))
            except Exception:
                pass
        venue_docs = await db.venues.find(
            {"_id": {"$in": venue_object_ids}}
        ).to_list(200)
        venues_map = {
            str(v["_id"]): {
                "name": v["name"],
                "default_image_url": v.get("default_image_url"),
            }
            for v in venue_docs
        }

    result = []
    for e in events:
        doc = _serialize_doc(e)
        venue_info = venues_map.get(doc.get("venue_id", ""), {})
        doc["venue_name"] = venue_info.get("name", "Unknown")
        if not doc.get("image_url"):
            doc["image_url"] = venue_info.get("default_image_url")
        result.append(doc)

    return result


@app.get("/events/{event_id}")
async def get_event(event_id: str):
    """Get a single event by ID."""
    db = get_db()
    event = await db.events.find_one({"_id": ObjectId(event_id)})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return _serialize_doc(event)
