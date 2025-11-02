#!/usr/bin/env python3
"""Validate CP surfaces VSM caps and preflight works.

This script checks that:
- GET /api/sources returns items with best-effort `caps` fields
  (codec/resolution/fps/pix_fmt/color_space) for at least one source
- POST /api/preflight evaluates the selected source against the first
  available graph's `requires` and returns an { ok, reasons[] } payload

Usage:

    python scripts/check_caps_and_preflight.py \
        --base http://127.0.0.1:8082 \
        --timeout 5

Exits 0 on success, non-zero otherwise.
"""

from __future__ import annotations

import argparse
import sys
from typing import Iterable, Optional

import requests


def get_json(base_url: str, path: str, timeout: float) -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    if not isinstance(j, dict) or not j.get("success", True):
        raise ValueError(f"GET {path} returned unexpected payload: {j!r}")
    return j


def post_json(base_url: str, path: str, payload: dict, timeout: float) -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    if not isinstance(j, dict) or not j.get("success", True):
        raise ValueError(f"POST {path} reported failure: {j!r}")
    return j


def pick_first_with_caps(items: list[dict]) -> Optional[dict]:
    for it in items:
        caps = (it or {}).get("caps")
        if isinstance(caps, dict):
            return it
    return None


def main(argv: Iterable[str]) -> int:
    ap = argparse.ArgumentParser(description="Check caps in /api/sources and preflight")
    ap.add_argument("--base", default="http://127.0.0.1:8082", help="Analysis API base URL")
    ap.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout seconds")
    args = ap.parse_args(list(argv))

    base = args.base.rstrip('/')
    try:
        # 1) sources should include caps for at least one entry
        src_resp = get_json(base, "/api/sources", args.timeout)
        items = src_resp.get("data")
        if not isinstance(items, list):
            # Some handlers return { data: { items: [] } }
            data = src_resp.get("data") or {}
            items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ValueError("/api/sources did not return a list of items")

        sel = pick_first_with_caps(items)
        if not sel:
            raise ValueError("no source item contains 'caps' in /api/sources response")
        print(f"[ok] /api/sources returned caps for at least one source (id={sel.get('id')})")

        # 2) pick a graph and run preflight
        graphs = get_json(base, "/api/graphs", args.timeout).get("data")
        if not isinstance(graphs, list) or not graphs:
            print("[warn] /api/graphs returned no graphs; skipping preflight")
            return 0
        graph = graphs[0]
        gid = graph.get("id") or graph.get("graph_id")
        requires = graph.get("requires")
        payload = {"source": sel}
        if gid: payload["graph_id"] = gid
        if requires: payload["requires"] = requires
        pf = post_json(base, "/api/preflight", payload, args.timeout)
        data = pf.get("data") or {}
        ok = bool((data or {}).get("ok"))
        reasons = (data or {}).get("reasons") or []
        print(f"[ok] preflight returned ok={ok} reasons={reasons}")
        return 0

    except Exception as exc:  # noqa: BLE001
        print(f"[error] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

