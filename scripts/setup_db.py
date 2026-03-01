"""One-time database setup: enable pgvector extension and create all tables."""

import asyncio
import sys

sys.path.insert(0, ".")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.models import Base


async def setup():
    print(f"Connecting to database...")
    engine = create_async_engine(settings.database_url, echo=True)

    async with engine.begin() as conn:
        # Enable pgvector
        print("\n--- Enabling pgvector extension ---")
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        print("✅ pgvector enabled")

        # Create all tables
        print("\n--- Creating tables ---")
        await conn.run_sync(Base.metadata.create_all)
        print("✅ All tables created")

    await engine.dispose()
    print("\n🎉 Database setup complete!")


if __name__ == "__main__":
    asyncio.run(setup())
