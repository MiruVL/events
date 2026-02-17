from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import settings

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongodb_uri)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    return get_client()[settings.mongodb_db]


async def init_db() -> None:
    """Create indexes for venues and events collections."""
    db = get_db()

    # Venues: 2dsphere index for geo queries, unique on google_place_id
    await db.venues.create_index([("location", "2dsphere")])
    await db.venues.create_index("google_place_id", unique=True, sparse=True)

    # Events: compound unique index for deduplication
    await db.events.create_index(
        [("venue_id", 1), ("date", 1), ("title", 1)],
        unique=True,
    )


async def close_db() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
