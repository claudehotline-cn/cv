"""
Idempotent reuse test for async subscriptions.

Steps:
 1) POST /api/subscriptions twice with the same stream_id/profile/url
 2) Expect the same subscription id to be returned
 3) Cancel the subscription
Exit codes: 0 on success; 2 on failure.
"""
from __future__ import annotations
import argparse
import time
import sys
import requests


def post_json(base: str, path: str, payload: dict, timeout: int, expect_status: int|None=None):
    r = requests.post(base + path, json=payload, timeout=timeout)
    if expect_status is not None and r.status_code != expect_status:
        raise RuntimeError(f"unexpected status {r.status_code}, want {expect_status}: {r.text[:200]}")
    r.raise_for_status()
    return r.json()


def delete_json(base: str, path: str, timeout: int, expect_status: int|None=None):
    r = requests.delete(base + path, timeout=timeout)
    if expect_status is not None and r.status_code != expect_status:
        raise RuntimeError(f"unexpected status {r.status_code}, want {expect_status}: {r.text[:200]}")
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8082")
    ap.add_argument("--profile", default="det_720p")
    ap.add_argument("--stream-id", default="async_idem_01")
    ap.add_argument("--url", default="video-analyzer/data/01.mp4")
    ap.add_argument("--timeout", type=int, default=10)
    args = ap.parse_args()

    payload = {"stream_id": args.stream_id, "profile": args.profile, "url": args.url}
    r1 = post_json(args.base, "/api/subscriptions", payload, args.timeout, expect_status=202)
    id1 = (r1.get("data") or {}).get("id")
    if not id1:
        print(f"[ERR] missing id in first response: {r1}")
        return 2
    # immediate second request: should reuse the same id
    r2 = post_json(args.base, "/api/subscriptions", payload, args.timeout, expect_status=202)
    id2 = (r2.get("data") or {}).get("id")
    if id1 != id2:
        print(f"[ERR] idempotent reuse failed: {id1} != {id2}")
        # best-effort cleanup
        try:
            delete_json(args.base, f"/api/subscriptions/{id1}", args.timeout, expect_status=202)
            delete_json(args.base, f"/api/subscriptions/{id2}", args.timeout, expect_status=202)
        except Exception:
            pass
        return 2

    # cleanup
    delete_json(args.base, f"/api/subscriptions/{id1}", args.timeout, expect_status=202)
    print(f"[PASS] idempotent id={id1}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

