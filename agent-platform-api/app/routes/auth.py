import os
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Body, Header, HTTPException
from agent_auth_client import AuthClient
from agent_core.settings import get_settings


router = APIRouter(prefix="/auth", tags=["auth"])


def _auth_base_url() -> str:
    return (os.getenv("AGENT_AUTH_URL") or "http://agent-auth:8000").rstrip("/")


async def _proxy(method: str, path: str, body: Dict[str, Any] | None = None, auth: str | None = None):
    url = _auth_base_url() + path
    headers: Dict[str, str] = {}
    if auth:
        headers["Authorization"] = auth

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(method, url, json=body, headers=headers)

    try:
        data = resp.json()
    except Exception:
        data = {"detail": resp.text or "Upstream error"}

    if resp.status_code >= 400:
        detail = data.get("detail", data)
        raise HTTPException(status_code=resp.status_code, detail=detail)

    return data


@router.post("/register")
async def register(body: Dict[str, Any] = Body(...)):
    return await _proxy("POST", "/auth/register", body=body)


@router.post("/login")
async def login(body: Dict[str, Any] = Body(...)):
    return await _proxy("POST", "/auth/login", body=body)


@router.post("/refresh")
async def refresh(body: Dict[str, Any] = Body(...)):
    return await _proxy("POST", "/auth/refresh", body=body)


@router.post("/logout")
async def logout(body: Dict[str, Any] = Body(...)):
    return await _proxy("POST", "/auth/logout", body=body)


@router.post("/logout-all")
async def logout_all(authorization: str | None = Header(default=None)):
    return await _proxy("POST", "/auth/logout-all", auth=authorization)


@router.get("/me")
async def me(authorization: str | None = Header(default=None)):
    data = await _proxy("GET", "/auth/me", auth=authorization)
    if not authorization:
        return data

    try:
        principal = await AuthClient(get_settings().auth_introspection_url).introspect(authorization=authorization)
        if isinstance(data, dict):
            data["tenant_id"] = principal.tenant_id
            data["tenant_role"] = principal.tenant_role
    except Exception:
        # Keep /auth/me available even if introspection is temporarily unavailable.
        pass

    return data


@router.post("/change-password")
async def change_password(body: Dict[str, Any] = Body(...), authorization: str | None = Header(default=None)):
    return await _proxy("POST", "/auth/change-password", body=body, auth=authorization)


@router.post("/api-keys")
async def create_api_key(body: Dict[str, Any] = Body(...), authorization: str | None = Header(default=None)):
    return await _proxy("POST", "/auth/api-keys", body=body, auth=authorization)


@router.get("/api-keys")
async def list_api_keys(authorization: str | None = Header(default=None)):
    return await _proxy("GET", "/auth/api-keys", auth=authorization)


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: str, authorization: str | None = Header(default=None)):
    return await _proxy("DELETE", f"/auth/api-keys/{key_id}", auth=authorization)
