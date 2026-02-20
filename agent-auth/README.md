# agent-auth

Independent authentication service for Agent Platform.

## Features (MVP)

- Email/password login with bcrypt
- JWT access token + refresh token rotation
- API key create/list/revoke
- Introspection endpoint for internal services
- MySQL as primary auth database (`agent_auth` schema)

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 18112
```

## Required env

- `AGENT_AUTH_DB_URL`
- `AGENT_AUTH_JWT_SECRET`
