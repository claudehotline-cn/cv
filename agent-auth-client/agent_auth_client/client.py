from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class AuthPrincipalDTO:
    user_id: str
    role: str
    email: str | None = None
    tenant_id: str | None = None
    tenant_role: str | None = None


class AuthClient:
    def __init__(self, introspection_url: str, timeout: float = 10.0):
        self._introspection_url = introspection_url
        self._timeout = timeout

    async def introspect(self, authorization: str | None = None, api_key: str | None = None) -> AuthPrincipalDTO:
        headers: dict[str, str] = {}
        if authorization:
            headers["Authorization"] = authorization
        if api_key:
            headers["X-Api-Key"] = api_key

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._introspection_url, headers=headers)
        except Exception as exc:
            raise RuntimeError("Auth service unavailable") from exc

        if resp.status_code >= 400:
            raise ValueError("Invalid authentication credentials")

        data = resp.json()
        if not data.get("active"):
            raise ValueError("Inactive principal")

        user_id = str(data.get("sub") or "").strip()
        if not user_id:
            raise ValueError("Invalid principal payload")

        role = str(data.get("role") or "user").strip().lower() or "user"
        email = data.get("email")
        tenant_id = data.get("tenant_id")
        tenant_role = data.get("tenant_role")
        return AuthPrincipalDTO(
            user_id=user_id,
            role=role,
            email=email,
            tenant_id=tenant_id,
            tenant_role=tenant_role,
        )
