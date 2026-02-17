"""Verify MongoDB connectivity and initialize indexes."""

import asyncio

from app.db import close_db, get_client, get_db, init_db


async def main() -> None:
    client = get_client()
    db = get_db()

    # Ping to verify connection
    result = await client.admin.command("ping")
    print(f"MongoDB ping: {result}")

    # Initialize indexes
    await init_db()
    print("Indexes created.")

    # Show existing collections
    collections = await db.list_collection_names()
    print(f"Collections in '{db.name}': {collections}")

    await close_db()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
