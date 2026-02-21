from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from agent_core.settings import get_settings

settings = get_settings()

# Ensure async driver
DATABASE_URL = settings.postgres_uri
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Lightweight schema migration for auth ownership FK model.
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS platform_users (
                user_id VARCHAR(100) PRIMARY KEY,
                email VARCHAR(255),
                role VARCHAR(20),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))

        await conn.execute(text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_id VARCHAR(100)"))
        await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS user_id VARCHAR(100)"))

        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id)"))

        await conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_sessions_user'
                ) THEN
                    ALTER TABLE sessions
                    ADD CONSTRAINT fk_sessions_user
                    FOREIGN KEY (user_id) REFERENCES platform_users(user_id);
                END IF;
            END $$;
        """))

        await conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_tasks_user'
                ) THEN
                    ALTER TABLE tasks
                    ADD CONSTRAINT fk_tasks_user
                    FOREIGN KEY (user_id) REFERENCES platform_users(user_id);
                END IF;
            END $$;
        """))

        # Backfill ownership from legacy session.state.owner_user_id
        await conn.execute(text("""
            INSERT INTO platform_users (user_id, role)
            SELECT DISTINCT state->>'owner_user_id' AS user_id, 'user' AS role
            FROM sessions
            WHERE state IS NOT NULL
              AND jsonb_typeof(state) = 'object'
              AND state ? 'owner_user_id'
              AND COALESCE(state->>'owner_user_id', '') <> ''
            ON CONFLICT (user_id) DO NOTHING
        """))

        await conn.execute(text("""
            UPDATE sessions
            SET user_id = state->>'owner_user_id'
            WHERE user_id IS NULL
              AND state IS NOT NULL
              AND jsonb_typeof(state) = 'object'
              AND state ? 'owner_user_id'
              AND COALESCE(state->>'owner_user_id', '') <> ''
        """))

        await conn.execute(text("""
            UPDATE tasks t
            SET user_id = s.user_id
            FROM sessions s
            WHERE t.user_id IS NULL AND t.session_id = s.id
        """))
