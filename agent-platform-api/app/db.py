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
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
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
            CREATE TABLE IF NOT EXISTS secrets (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL,
                owner_user_id VARCHAR(100),
                scope VARCHAR(20) NOT NULL DEFAULT 'user',
                name VARCHAR(200) NOT NULL,
                provider VARCHAR(50),
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                current_version INT NOT NULL DEFAULT 1,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT uq_secrets_tenant_scope_owner_name UNIQUE (tenant_id, scope, owner_user_id, name),
                CONSTRAINT fk_secrets_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id),
                CONSTRAINT fk_secrets_owner FOREIGN KEY (owner_user_id) REFERENCES platform_users(user_id)
            )
        """))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS secret_versions (
                id UUID PRIMARY KEY,
                secret_id UUID NOT NULL,
                version INT NOT NULL,
                crypto_alg VARCHAR(50) NOT NULL DEFAULT 'aes_gcm_v1',
                key_ref VARCHAR(100) NOT NULL,
                nonce TEXT NOT NULL,
                ciphertext TEXT NOT NULL,
                enc_meta JSONB,
                fingerprint VARCHAR(64),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT uq_secret_versions_secret_version UNIQUE (secret_id, version),
                CONSTRAINT fk_secret_versions_secret FOREIGN KEY (secret_id) REFERENCES secrets(id)
            )
        """))

        # --- Agent Versions ---
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_versions (
                id UUID PRIMARY KEY,
                agent_id UUID NOT NULL,
                version INT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'draft',
                config JSONB NOT NULL DEFAULT '{}',
                change_summary TEXT,
                created_by VARCHAR(100),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                published_at TIMESTAMPTZ,
                CONSTRAINT uq_agent_versions_agent_version UNIQUE (agent_id, version),
                CONSTRAINT fk_agent_versions_agent FOREIGN KEY (agent_id) REFERENCES agents(id),
                CONSTRAINT fk_agent_versions_created_by FOREIGN KEY (created_by) REFERENCES platform_users(user_id)
            )
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_versions_agent_id ON agent_versions(agent_id)"))
        await conn.execute(text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS published_version_id UUID"))
        await conn.execute(text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS draft_version_id UUID"))

        # --- Prompt Templates & Versions ---
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prompt_templates (
                id UUID PRIMARY KEY,
                tenant_id UUID,
                key VARCHAR(200) NOT NULL,
                name VARCHAR(200) NOT NULL,
                description TEXT,
                category VARCHAR(50),
                published_version_id UUID,
                draft_version_id UUID,
                created_by VARCHAR(100),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT uq_prompt_templates_tenant_key UNIQUE (tenant_id, key),
                CONSTRAINT fk_prompt_templates_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id),
                CONSTRAINT fk_prompt_templates_created_by FOREIGN KEY (created_by) REFERENCES platform_users(user_id)
            )
        """))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prompt_versions (
                id UUID PRIMARY KEY,
                template_id UUID NOT NULL,
                version INT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'draft',
                content TEXT NOT NULL,
                variables_schema JSONB,
                change_summary TEXT,
                created_by VARCHAR(100),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                published_at TIMESTAMPTZ,
                CONSTRAINT uq_prompt_versions_template_version UNIQUE (template_id, version),
                CONSTRAINT fk_prompt_versions_template FOREIGN KEY (template_id) REFERENCES prompt_templates(id),
                CONSTRAINT fk_prompt_versions_created_by FOREIGN KEY (created_by) REFERENCES platform_users(user_id)
            )
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_prompt_versions_template_id ON prompt_versions(template_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_prompt_templates_tenant_id ON prompt_templates(tenant_id)"))
        # Partial unique index for builtin prompts (tenant_id IS NULL)
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_prompt_templates_builtin_key ON prompt_templates(key) WHERE tenant_id IS NULL"))

        # --- Prompt A/B Tests ---
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prompt_ab_tests (
                id UUID PRIMARY KEY,
                template_id UUID NOT NULL,
                name VARCHAR(200) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'running',
                variant_a_id UUID NOT NULL,
                variant_b_id UUID NOT NULL,
                traffic_split REAL NOT NULL DEFAULT 0.5,
                metrics JSONB NOT NULL DEFAULT '{}',
                winner_version_id UUID,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                ended_at TIMESTAMPTZ,
                CONSTRAINT fk_prompt_ab_tests_template FOREIGN KEY (template_id) REFERENCES prompt_templates(id),
                CONSTRAINT fk_prompt_ab_tests_variant_a FOREIGN KEY (variant_a_id) REFERENCES prompt_versions(id),
                CONSTRAINT fk_prompt_ab_tests_variant_b FOREIGN KEY (variant_b_id) REFERENCES prompt_versions(id),
                CONSTRAINT fk_prompt_ab_tests_winner FOREIGN KEY (winner_version_id) REFERENCES prompt_versions(id)
            )
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_prompt_ab_tests_template_id ON prompt_ab_tests(template_id)"))

        # --- Phase2 Guardrails + Semantic Cache ---
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tenant_guardrail_policies (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL UNIQUE,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                mode VARCHAR(20) NOT NULL DEFAULT 'monitor',
                config JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT fk_tenant_guardrail_policies_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id)
            )
        """))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS guardrail_events (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL,
                request_id UUID,
                direction VARCHAR(20) NOT NULL,
                action VARCHAR(20) NOT NULL,
                reason_code VARCHAR(100),
                payload JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT fk_guardrail_events_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id),
                CONSTRAINT fk_guardrail_events_request FOREIGN KEY (request_id) REFERENCES agent_runs(request_id)
            )
        """))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS semantic_cache_entries (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL,
                namespace VARCHAR(100) NOT NULL DEFAULT 'default',
                prompt_hash VARCHAR(64) NOT NULL,
                response TEXT NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{}',
                embedding vector(1024),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT fk_semantic_cache_entries_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id)
            )
        """))

        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_guardrail_events_tenant_id ON guardrail_events(tenant_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_guardrail_events_request_id ON guardrail_events(request_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_guardrail_events_created_at ON guardrail_events(created_at DESC)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_semantic_cache_entries_lookup ON semantic_cache_entries(tenant_id, namespace, prompt_hash)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_semantic_cache_entries_embedding ON semantic_cache_entries USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"))

        # --- Eval Core ---
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eval_datasets (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL,
                agent_id UUID NOT NULL,
                name VARCHAR(200) NOT NULL,
                description TEXT,
                created_by VARCHAR(100),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT fk_eval_datasets_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id),
                CONSTRAINT fk_eval_datasets_agent FOREIGN KEY (agent_id) REFERENCES agents(id),
                CONSTRAINT fk_eval_datasets_created_by FOREIGN KEY (created_by) REFERENCES platform_users(user_id)
            )
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_eval_datasets_tenant_id ON eval_datasets(tenant_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_eval_datasets_agent_id ON eval_datasets(agent_id)"))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eval_cases (
                id UUID PRIMARY KEY,
                dataset_id UUID NOT NULL,
                input JSONB NOT NULL,
                expected_output JSONB,
                tags JSONB NOT NULL DEFAULT '[]',
                notes TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT fk_eval_cases_dataset FOREIGN KEY (dataset_id) REFERENCES eval_datasets(id) ON DELETE CASCADE
            )
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_eval_cases_dataset_id ON eval_cases(dataset_id)"))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eval_runs (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL,
                dataset_id UUID NOT NULL,
                agent_id UUID NOT NULL,
                agent_version INT NOT NULL,
                prompt_version_snapshot JSONB,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                config JSONB NOT NULL DEFAULT '{}',
                summary JSONB,
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT fk_eval_runs_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id),
                CONSTRAINT fk_eval_runs_dataset FOREIGN KEY (dataset_id) REFERENCES eval_datasets(id),
                CONSTRAINT fk_eval_runs_agent FOREIGN KEY (agent_id) REFERENCES agents(id)
            )
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_eval_runs_agent_id ON eval_runs(agent_id)"))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eval_results (
                id UUID PRIMARY KEY,
                run_id UUID NOT NULL,
                case_id UUID NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                actual_output JSONB,
                trajectory JSONB,
                scores JSONB NOT NULL DEFAULT '{}',
                error_message TEXT,
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                CONSTRAINT fk_eval_results_run FOREIGN KEY (run_id) REFERENCES eval_runs(id) ON DELETE CASCADE,
                CONSTRAINT fk_eval_results_case FOREIGN KEY (case_id) REFERENCES eval_cases(id)
            )
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_eval_results_run_id ON eval_results(run_id)"))

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
