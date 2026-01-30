"""vLLM OpenAI-compatible client helpers.

vLLM-omni exposes an OpenAI-compatible API (e.g. /v1/chat/completions).
We use httpx directly to avoid extra SDK dependencies.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

import httpx


logger = logging.getLogger(__name__)


def _normalize_base_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("vLLM base_url is empty")
    # Accept both http://host:port and http://host:port/v1
    if base.endswith("/v1"):
        return base
    return base + "/v1"


def image_to_data_url(image: Union[bytes, str, Path], mime_type: str = "image/jpeg") -> str:
    if isinstance(image, bytes):
        data = image
    else:
        p = Path(str(image))
        if p.exists():
            data = p.read_bytes()
        else:
            # Already a data URL or base64?
            s = str(image)
            if s.startswith("data:"):
                return s
            try:
                # if it's raw base64, wrap it
                base64.b64decode(s, validate=True)
                return f"data:{mime_type};base64,{s}"
            except Exception:
                raise ValueError("Unsupported image input")

    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


def _auth_headers(api_key: Optional[str]) -> Dict[str, str]:
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


async def chat_completion(
    *,
    base_url: str,
    api_key: Optional[str],
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    timeout_sec: int = 180,
) -> str:
    url = _normalize_base_url(base_url) + "/chat/completions"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
        "stream": False,
    }
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)

    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        resp = await client.post(url, json=payload, headers=_auth_headers(api_key))
        resp.raise_for_status()
        data = resp.json()

    try:
        return data["choices"][0]["message"]["content"] or ""
    except Exception as e:
        logger.error("Unexpected vLLM response: %s", data)
        raise RuntimeError(f"Invalid vLLM response format: {e}")


async def chat_completion_stream(
    *,
    base_url: str,
    api_key: Optional[str],
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    timeout_sec: int = 180,
) -> AsyncGenerator[str, None]:
    url = _normalize_base_url(base_url) + "/chat/completions"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
        "stream": True,
    }
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)

    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        async with client.stream("POST", url, json=payload, headers=_auth_headers(api_key)) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue
                data_str = line[len("data:") :].strip()
                if data_str == "[DONE]":
                    break

                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                try:
                    delta = chunk["choices"][0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content
                except Exception:
                    continue
