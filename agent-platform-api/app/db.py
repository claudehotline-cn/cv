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

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tenants (
                id UUID PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tenant_memberships (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL,
                user_id VARCHAR(100) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'member',
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT uq_tenant_memberships_tenant_user UNIQUE (tenant_id, user_id),
                CONSTRAINT fk_tenant_memberships_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id),
                CONSTRAINT fk_tenant_memberships_user FOREIGN KEY (user_id) REFERENCES platform_users(user_id)
            )
        """))

        await conn.execute(text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS tenant_id UUID"))
        await conn.execute(text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_id VARCHAR(100)"))
        await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS tenant_id UUID"))
        await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS user_id VARCHAR(100)"))
        await conn.execute(text("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS tenant_id UUID"))
        await conn.execute(text("ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS tenant_id UUID"))
        await conn.execute(text("ALTER TABLE auth_audit_events ADD COLUMN IF NOT EXISTS tenant_id UUID"))

        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sessions_tenant_id ON sessions(tenant_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tasks_tenant_id ON tasks(tenant_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_runs_tenant_id ON agent_runs(tenant_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_events_tenant_id ON audit_events(tenant_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_auth_audit_events_tenant_id ON auth_audit_events(tenant_id)"))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tenant_rate_limit_policies (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL UNIQUE,
                read_limit VARCHAR(20) NOT NULL DEFAULT '300/min',
                write_limit VARCHAR(20) NOT NULL DEFAULT '120/min',
                execute_limit VARCHAR(20) NOT NULL DEFAULT '60/min',
                user_read_limit VARCHAR(20) NOT NULL DEFAULT '120/min',
                user_write_limit VARCHAR(20) NOT NULL DEFAULT '60/min',
                user_execute_limit VARCHAR(20) NOT NULL DEFAULT '20/min',
                tenant_concurrency_limit INT NOT NULL DEFAULT 20,
                user_concurrency_limit INT NOT NULL DEFAULT 5,
                fail_mode VARCHAR(20) NOT NULL DEFAULT 'open',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT fk_tenant_rate_limit_policies_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id)
            )
        """))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tenant_quota_policies (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL UNIQUE,
                monthly_token_quota BIGINT NOT NULL DEFAULT 50000000,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT fk_tenant_quota_policies_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id)
            )
        """))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tenant_quota_usages (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL,
                period VARCHAR(7) NOT NULL,
                prompt_tokens BIGINT NOT NULL DEFAULT 0,
                completion_tokens BIGINT NOT NULL DEFAULT 0,
                total_tokens BIGINT NOT NULL DEFAULT 0,
                request_count BIGINT NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT uq_tenant_quota_usages_tenant_period UNIQUE (tenant_id, period),
                CONSTRAINT fk_tenant_quota_usages_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id)
            )
        """))

        await conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_sessions_tenant'
                ) THEN
                    ALTER TABLE sessions
                    ADD CONSTRAINT fk_sessions_tenant
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id);
                END IF;

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
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_tasks_tenant'
                ) THEN
                    ALTER TABLE tasks
                    ADD CONSTRAINT fk_tasks_tenant
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id);
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_tasks_user'
                ) THEN
                    ALTER TABLE tasks
                    ADD CONSTRAINT fk_tasks_user
                    FOREIGN KEY (user_id) REFERENCES platform_users(user_id);
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_agent_runs_tenant'
                ) THEN
                    ALTER TABLE agent_runs
                    ADD CONSTRAINT fk_agent_runs_tenant
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id);
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_audit_events_tenant'
                ) THEN
                    ALTER TABLE audit_events
                    ADD CONSTRAINT fk_audit_events_tenant
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id);
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_auth_audit_events_tenant'
                ) THEN
                    ALTER TABLE auth_audit_events
                    ADD CONSTRAINT fk_auth_audit_events_tenant
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id);
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

        # Ensure one default tenant and backfill tenant columns.
        default_tenant_id = settings.auth_default_tenant_id
        await conn.execute(text("""
            INSERT INTO tenants (id, name, status)
            VALUES (CAST(:tenant_id AS UUID), 'default-tenant', 'active')
            ON CONFLICT (id) DO NOTHING
        """), {"tenant_id": default_tenant_id})

        await conn.execute(text("""
            UPDATE sessions
            SET tenant_id = CAST(:tenant_id AS UUID)
            WHERE tenant_id IS NULL
        """), {"tenant_id": default_tenant_id})

        await conn.execute(text("""
            UPDATE tasks
            SET tenant_id = CAST(:tenant_id AS UUID)
            WHERE tenant_id IS NULL
        """), {"tenant_id": default_tenant_id})

        await conn.execute(text("""
            UPDATE agent_runs
            SET tenant_id = CAST(:tenant_id AS UUID)
            WHERE tenant_id IS NULL
        """), {"tenant_id": default_tenant_id})

        await conn.execute(text("""
            UPDATE audit_events
            SET tenant_id = COALESCE(
                (SELECT ar.tenant_id FROM agent_runs ar WHERE ar.request_id = audit_events.request_id),
                CAST(:tenant_id AS UUID)
            )
            WHERE tenant_id IS NULL
        """), {"tenant_id": default_tenant_id})

        await conn.execute(text("""
            UPDATE auth_audit_events
            SET tenant_id = CAST(COALESCE(payload->>'tenant_id', :tenant_id) AS UUID)
            WHERE tenant_id IS NULL
        """), {"tenant_id": default_tenant_id})

        await conn.execute(text("""
            INSERT INTO tenant_memberships (id, tenant_id, user_id, role, status)
            SELECT gen_random_uuid(), CAST(:tenant_id AS UUID), user_id,
                   CASE WHEN role = 'admin' THEN 'owner' ELSE 'member' END,
                   'active'
            FROM platform_users
            WHERE user_id IS NOT NULL
            ON CONFLICT (tenant_id, user_id) DO NOTHING
        """), {"tenant_id": default_tenant_id})

        await conn.execute(text("ALTER TABLE sessions ALTER COLUMN tenant_id SET NOT NULL"))
        await conn.execute(text("ALTER TABLE tasks ALTER COLUMN tenant_id SET NOT NULL"))
        await conn.execute(text("ALTER TABLE agent_runs ALTER COLUMN tenant_id SET NOT NULL"))
        await conn.execute(text("ALTER TABLE audit_events ALTER COLUMN tenant_id SET NOT NULL"))
        await conn.execute(text("ALTER TABLE auth_audit_events ALTER COLUMN tenant_id SET NOT NULL"))
