from __future__ import annotations

import asyncio
from typing import Optional
from uuid import uuid4

import pymysql
from pymysql.cursors import DictCursor

from agent_core.settings import get_settings

from ..ports.secrets import SecretMetadata, SecretRepository, SecretVersionData


class MySQLSecretRepository(SecretRepository):
    def __init__(self):
        self.settings = get_settings()
        self._schema_ready = False

    def _connect(self):
        return pymysql.connect(
            host=self.settings.db_host,
            port=int(self.settings.db_port),
            user=self.settings.db_user,
            password=self.settings.db_password,
            database=self.settings.db_default_name,
            autocommit=True,
            cursorclass=DictCursor,
            charset="utf8mb4",
        )

    def _ensure_schema_sync(self) -> None:
        if self._schema_ready:
            return
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS secrets (
                      id CHAR(36) PRIMARY KEY,
                      tenant_id CHAR(36) NOT NULL,
                      owner_user_id VARCHAR(100) NULL,
                      scope VARCHAR(20) NOT NULL DEFAULT 'user',
                      name VARCHAR(200) NOT NULL,
                      provider VARCHAR(50) NULL,
                      status VARCHAR(20) NOT NULL DEFAULT 'active',
                      current_version INT NOT NULL DEFAULT 1,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                      UNIQUE KEY uq_secrets_tenant_scope_owner_name (tenant_id, scope, owner_user_id, name),
                      KEY idx_secrets_tenant_name (tenant_id, name)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS secret_versions (
                      id CHAR(36) PRIMARY KEY,
                      secret_id CHAR(36) NOT NULL,
                      version INT NOT NULL,
                      crypto_alg VARCHAR(50) NOT NULL DEFAULT 'aes_gcm_v1',
                      key_ref VARCHAR(100) NOT NULL,
                      nonce TEXT NOT NULL,
                      ciphertext LONGTEXT NOT NULL,
                      enc_meta JSON NULL,
                      fingerprint VARCHAR(64) NULL,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      UNIQUE KEY uq_secret_versions_secret_version (secret_id, version),
                      KEY idx_secret_versions_secret_id (secret_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            self._schema_ready = True
        finally:
            conn.close()

    async def _ensure_schema(self) -> None:
        await asyncio.to_thread(self._ensure_schema_sync)

    @staticmethod
    def _meta_from_row(row: dict) -> SecretMetadata:
        return SecretMetadata(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            owner_user_id=row.get("owner_user_id"),
            scope=row["scope"],
            name=row["name"],
            provider=row.get("provider"),
            status=row["status"],
            current_version=int(row["current_version"]),
        )

    @staticmethod
    def _version_from_row(row: dict) -> SecretVersionData:
        return SecretVersionData(
            id=str(row["id"]),
            secret_id=str(row["secret_id"]),
            version=int(row["version"]),
            crypto_alg=row["crypto_alg"],
            key_ref=row["key_ref"],
            nonce=row["nonce"],
            ciphertext=row["ciphertext"],
            enc_meta=row.get("enc_meta"),
            fingerprint=row.get("fingerprint"),
        )

    def _create_secret_sync(
        self,
        *,
        tenant_id: str,
        owner_user_id: Optional[str],
        scope: str,
        name: str,
        provider: Optional[str],
    ) -> SecretMetadata:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM secrets
                    WHERE tenant_id=%s AND scope=%s AND owner_user_id <=> %s AND name=%s AND status<>'deleted'
                    LIMIT 1
                    """,
                    (tenant_id, scope, owner_user_id, name),
                )
                existing = cur.fetchone()
                if existing:
                    raise ValueError("Secret already exists")

                secret_id = str(uuid4())
                cur.execute(
                    """
                    INSERT INTO secrets(id, tenant_id, owner_user_id, scope, name, provider, status, current_version)
                    VALUES(%s,%s,%s,%s,%s,%s,'active',1)
                    """,
                    (secret_id, tenant_id, owner_user_id, scope, name, provider),
                )
                return SecretMetadata(
                    id=secret_id,
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    scope=scope,
                    name=name,
                    provider=provider,
                    status="active",
                    current_version=1,
                )
        finally:
            conn.close()

    async def create_secret(self, *, tenant_id: str, owner_user_id: Optional[str], scope: str, name: str, provider: Optional[str]) -> SecretMetadata:
        await self._ensure_schema()
        return await asyncio.to_thread(
            self._create_secret_sync,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            scope=scope,
            name=name,
            provider=provider,
        )

    def _append_version_sync(
        self,
        *,
        secret_id: str,
        version: int,
        crypto_alg: str,
        key_ref: str,
        nonce: str,
        ciphertext: str,
        enc_meta: Optional[dict],
        fingerprint: Optional[str],
    ) -> SecretVersionData:
        import json

        conn = self._connect()
        try:
            with conn.cursor() as cur:
                version_id = str(uuid4())
                cur.execute(
                    """
                    INSERT INTO secret_versions(id, secret_id, version, crypto_alg, key_ref, nonce, ciphertext, enc_meta, fingerprint)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (version_id, secret_id, version, crypto_alg, key_ref, nonce, ciphertext, json.dumps(enc_meta) if enc_meta else None, fingerprint),
                )
                return SecretVersionData(
                    id=version_id,
                    secret_id=secret_id,
                    version=version,
                    crypto_alg=crypto_alg,
                    key_ref=key_ref,
                    nonce=nonce,
                    ciphertext=ciphertext,
                    enc_meta=enc_meta,
                    fingerprint=fingerprint,
                )
        finally:
            conn.close()

    async def append_version(self, *, secret_id: str, version: int, crypto_alg: str, key_ref: str, nonce: str, ciphertext: str, enc_meta: Optional[dict], fingerprint: Optional[str]) -> SecretVersionData:
        await self._ensure_schema()
        return await asyncio.to_thread(
            self._append_version_sync,
            secret_id=secret_id,
            version=version,
            crypto_alg=crypto_alg,
            key_ref=key_ref,
            nonce=nonce,
            ciphertext=ciphertext,
            enc_meta=enc_meta,
            fingerprint=fingerprint,
        )

    def _get_secret_metadata_sync(self, *, tenant_id: str, secret_id: str) -> Optional[SecretMetadata]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, tenant_id, owner_user_id, scope, name, provider, status, current_version
                    FROM secrets
                    WHERE id=%s AND tenant_id=%s AND status<>'deleted'
                    LIMIT 1
                    """,
                    (secret_id, tenant_id),
                )
                row = cur.fetchone()
                return self._meta_from_row(row) if row else None
        finally:
            conn.close()

    async def get_secret_metadata(self, *, tenant_id: str, secret_id: str) -> Optional[SecretMetadata]:
        await self._ensure_schema()
        return await asyncio.to_thread(self._get_secret_metadata_sync, tenant_id=tenant_id, secret_id=secret_id)

    def _list_metadata_sync(self, *, tenant_id: str, owner_user_id: Optional[str], scope: Optional[str]) -> list[SecretMetadata]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                sql = (
                    "SELECT id, tenant_id, owner_user_id, scope, name, provider, status, current_version "
                    "FROM secrets WHERE tenant_id=%s AND status<>'deleted'"
                )
                params: list = [tenant_id]
                if owner_user_id:
                    sql += " AND (owner_user_id=%s OR scope='tenant')"
                    params.append(owner_user_id)
                if scope:
                    sql += " AND scope=%s"
                    params.append(scope)
                sql += " ORDER BY created_at DESC"
                cur.execute(sql, tuple(params))
                rows = cur.fetchall() or []
                return [self._meta_from_row(r) for r in rows]
        finally:
            conn.close()

    async def list_metadata(self, *, tenant_id: str, owner_user_id: Optional[str], scope: Optional[str]) -> list[SecretMetadata]:
        await self._ensure_schema()
        return await asyncio.to_thread(
            self._list_metadata_sync,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            scope=scope,
        )

    def _find_by_ref_sync(self, *, tenant_id: str, user_id: str, name: str) -> Optional[SecretMetadata]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, tenant_id, owner_user_id, scope, name, provider, status, current_version
                    FROM secrets
                    WHERE tenant_id=%s AND name=%s AND scope='user' AND owner_user_id=%s AND status='active'
                    LIMIT 1
                    """,
                    (tenant_id, name, user_id),
                )
                row = cur.fetchone()
                if row:
                    return self._meta_from_row(row)
                cur.execute(
                    """
                    SELECT id, tenant_id, owner_user_id, scope, name, provider, status, current_version
                    FROM secrets
                    WHERE tenant_id=%s AND name=%s AND scope='tenant' AND status='active'
                    LIMIT 1
                    """,
                    (tenant_id, name),
                )
                row = cur.fetchone()
                return self._meta_from_row(row) if row else None
        finally:
            conn.close()

    async def find_by_ref(self, *, tenant_id: str, user_id: str, name: str) -> Optional[SecretMetadata]:
        await self._ensure_schema()
        return await asyncio.to_thread(self._find_by_ref_sync, tenant_id=tenant_id, user_id=user_id, name=name)

    def _get_version_sync(self, *, secret_id: str, version: int) -> Optional[SecretVersionData]:
        import json

        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, secret_id, version, crypto_alg, key_ref, nonce, ciphertext, enc_meta, fingerprint
                    FROM secret_versions
                    WHERE secret_id=%s AND version=%s
                    LIMIT 1
                    """,
                    (secret_id, version),
                )
                row = cur.fetchone()
                if not row:
                    return None
                enc_meta = row.get("enc_meta")
                if isinstance(enc_meta, str):
                    try:
                        row["enc_meta"] = json.loads(enc_meta)
                    except Exception:
                        row["enc_meta"] = None
                return self._version_from_row(row)
        finally:
            conn.close()

    async def get_version(self, *, secret_id: str, version: int) -> Optional[SecretVersionData]:
        await self._ensure_schema()
        return await asyncio.to_thread(self._get_version_sync, secret_id=secret_id, version=version)

    def _set_current_version_sync(self, *, secret_id: str, version: int) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE secrets SET current_version=%s WHERE id=%s", (version, secret_id))
        finally:
            conn.close()

    async def set_current_version(self, *, secret_id: str, version: int) -> None:
        await self._ensure_schema()
        await asyncio.to_thread(self._set_current_version_sync, secret_id=secret_id, version=version)

    def _set_status_sync(self, *, secret_id: str, status: str) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE secrets SET status=%s WHERE id=%s", (status, secret_id))
        finally:
            conn.close()

    async def set_status(self, *, secret_id: str, status: str) -> None:
        await self._ensure_schema()
        await asyncio.to_thread(self._set_status_sync, secret_id=secret_id, status=status)
