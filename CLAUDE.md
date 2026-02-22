# CLAUDE.md

## Scope
This repository is a multi-service monorepo for Agent Platform, including backend APIs, worker services, plugin packages, and frontend UIs.

## Working Rules
- Run backend tests in the `agent-test` container.
- For frontend checks, run build commands inside `agent-chat-vue`.
- Prefer editing code in the active worktree when feature work is in progress.
- Do not edit generated/vendor code under `third-party/` unless explicitly requested.

## Key Directories
- `agent-platform-api/`: FastAPI control-plane API (main backend for agent management/chat routes).
- `agent-chat-vue/`: Vue 3 frontend for the platform UI.
- `agent-core/`: shared runtime/settings/middleware/events abstractions.
- `agent-audit/`: audit emitter/instrumentation package.
- `agent-test/`: test package and containerized test runtime.
- `agent-plugins/`: plugin implementations and prompt constants.
- `docker/compose/docker-compose.yml`: primary local development stack definition.

## Common Commands
- Start stack:
  - `docker compose -f docker/compose/docker-compose.yml up -d`
- Run one backend test file (inside container):
  - `docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/<test_file>.py -q`
- Run frontend build:
  - `cd agent-chat-vue && npm run build`

## Test Notes
- The API code imports modules from multiple local packages (`agent-core`, `agent-audit`), so pytest runs from host shell often fail unless `PYTHONPATH` is set.
- Use `agent-test` as the default test runner to avoid host environment drift.

## Current Architecture Notes
- `agent-platform-api/app/db.py` uses inline SQL migrations in `init_db()` (no Alembic in current flow).
- Prompt management (W2) is implemented in:
  - `agent-platform-api/app/routes/prompts.py`
  - `agent-platform-api/app/core/prompt_resolver.py`
  - `agent-platform-api/app/models/db_models.py`
- Prompt builtin sync is performed by `agent-platform-api/app/core/agent_registry.py` during startup.

## W3 In-Flight Work
- Add Prompt A/B and Eval core schema/API flow.
- Keep schema additions aligned between:
  - ORM models in `agent-platform-api/app/models/db_models.py`
  - inline migration SQL in `agent-platform-api/app/db.py`
  - migration contract tests in `agent-platform-api/test/`

## Safety
- Avoid destructive git commands unless explicitly requested.
- Never commit secrets or local credential files.
