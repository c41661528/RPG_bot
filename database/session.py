from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import DATABASE_URL
from models.base import Base

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)
AsyncSessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# Raw SQL migrations for new columns added after initial release.
_MIGRATIONS = [
    "ALTER TABLE characters ADD COLUMN IF NOT EXISTS medkits INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE characters ADD COLUMN IF NOT EXISTS inventory JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE characters ADD COLUMN IF NOT EXISTS equipped_weapon VARCHAR(60)",
    "ALTER TABLE characters ADD COLUMN IF NOT EXISTS equipped_armor VARCHAR(60)",
    "ALTER TABLE characters ADD COLUMN IF NOT EXISTS kills INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE characters ADD COLUMN IF NOT EXISTS item_enhancements JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE characters ADD COLUMN IF NOT EXISTS quests JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE characters ADD COLUMN IF NOT EXISTS energy_cells INTEGER NOT NULL DEFAULT 0",
    # Sprint 7 migrations
    "ALTER TABLE characters ADD COLUMN IF NOT EXISTS equipped_helmet VARCHAR(60)",
    "ALTER TABLE characters ADD COLUMN IF NOT EXISTS equipped_accessory VARCHAR(60)",
    "ALTER TABLE characters ADD COLUMN IF NOT EXISTS materials JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE characters ADD COLUMN IF NOT EXISTS weekly_quests JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE characters ADD COLUMN IF NOT EXISTS achievements JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE characters ADD COLUMN IF NOT EXISTS dungeon_state JSONB NOT NULL DEFAULT '{}'::jsonb",
]


async def init_db() -> None:
    """Create all tables then apply incremental column migrations."""
    import models  # noqa: F401 — registers all ORM models with Base.metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for sql in _MIGRATIONS:
            await conn.execute(text(sql))
