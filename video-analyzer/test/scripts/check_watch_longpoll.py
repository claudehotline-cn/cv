#!/usr/bin/env python3
"""Exercise long-poll watch endpoints for sources/logs/events.

Steps:
- GET /api/sources/watch to obtain initial rev
- Trigger a subscribe/unsubscribe to cause state change
- Verify watch endpoints return a new rev and valid items structure

Usage:
  python scripts/check_watch_longpoll.py \
    --base http://127.0.0.1:8082 \
    --url rtsp://127.0.0.1:8554/camera_01
"""

from __future__ import annotations

import argparse
import time
import uuid
from typing import Iterable, Dict, Any

import requests


def get_json(base: str, path: str, timeout: float) -> Dict[str, Any]:
    r = requests.get(base.rstrip('/') + path, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    if not isinstance(j, dict):
        raise ValueError(f"GET {path} returned non-object: {j!r}")
    return j


def post_json(base: str, path: str, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    r = requests.post(base.rstrip('/') + path, json=payload, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    if not isinstance(j, dict):
        raise ValueError(f"POST {path} returned non-object: {j!r}")
    return j


def extract_rev_and_items(j: Dict[str, Any]) -> tuple[int, list]:
    d = j.get("data") if isinstance(j, dict) else None
    if isinstance(d, dict):
        rev = int(d.get("rev") or 0)
        items = d.get("items")
        if not isinstance(items, list):
            items = []
        return rev, items
    # Some handlers respond directly with { rev, items }
    rev = int(j.get("rev") or 0)
    items = j.get("items") if isinstance(j.get("items"), list) else []
    return rev, items


def main(argv: Iterable[str]) -> int:
    ap = argparse.ArgumentParser(description="Check watch endpoints long-poll")
    ap.add_argument("--base", default="http://127.0.0.1:8082")
    ap.add_argument("--url", required=True)
    ap.add_argument("--timeout", type=float, default=8.0)
    args = ap.parse_args(list(argv))

    base = args.base.rstrip('/')
    stream_id = f"watch_{int(time.time())}_{uuid.uuid4().hex[:6]}"

    # system info sanity
    get_json(base, "/api/system/info", args.timeout)

    # sources watch initial
    j0 = get_json(base, "/api/sources/watch?timeout_ms=1500&interval_ms=200", args.timeout)
    rev0, items0 = extract_rev_and_items(j0)
    print(f"[sources] initial rev={rev0} items={len(items0)}")

    # trigger subscribe
    profs = get_json(base, "/api/profiles", args.timeout).get("data") or []
    if not profs:
        raise ValueError("/api/profiles returned empty")
    profile = profs[0].get("name")
    subscribe_payload = {"stream": stream_id, "profile": profile, "url": args.url}
    post_json(base, "/api/subscribe", subscribe_payload, args.timeout)
    print(f"[subscribe] stream={stream_id} profile={profile}")

    # expect rev change
    time.sleep(0.5)
    j1 = get_json(base, f"/api/sources/watch?since={rev0}&timeout_ms=5000&interval_ms=200", args.timeout + 4)
    rev1, items1 = extract_rev_and_items(j1)
    if not rev1 or rev1 == rev0:
        raise RuntimeError("/api/sources/watch did not observe rev change after subscribe")
    print(f"[sources] changed rev={rev1} items={len(items1)}")

    # logs watch
    j2 = get_json(base, "/api/logs/watch?timeout_ms=1000&interval_ms=200", args.timeout)
    lrev0, _ = extract_rev_and_items(j2)
    j3 = get_json(base, f"/api/logs/watch?since={lrev0}&timeout_ms=3000&interval_ms=200", args.timeout+3)
    lrev1, lits = extract_rev_and_items(j3)
    print(f"[logs] rev0={lrev0} -> rev1={lrev1} items={len(lits)}")

    # events watch
    j4 = get_json(base, "/api/events/watch?timeout_ms=1000&interval_ms=200", args.timeout)
    erev0, _ = extract_rev_and_items(j4)
    j5 = get_json(base, f"/api/events/watch?since={erev0}&timeout_ms=3000&interval_ms=200", args.timeout+3)
    erev1, eits = extract_rev_and_items(j5)
    print(f"[events] rev0={erev0} -> rev1={erev1} items={len(eits)}")

    # cleanup
    post_json(base, "/api/unsubscribe", {"stream": stream_id, "profile": profile}, args.timeout)
    print("[cleanup] unsubscribed")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))

