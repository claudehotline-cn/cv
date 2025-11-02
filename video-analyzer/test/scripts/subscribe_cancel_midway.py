"""
Cancel in-flight async subscription test.

Steps:
 1) POST /api/subscriptions
 2) Immediately DELETE /api/subscriptions/{id}
 3) Poll GET until phase=cancelled (or timeout)
Exit codes: 0 on success; 2 on failure.
"""
from __future__ import annotations
import argparse
import time
import sys
import requests


def get_json(base: str, path: str, timeout: int):
    r = requests.get(base + path, timeout=timeout)
    r.raise_for_status()
    return r.json()


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
    ap.add_argument("--stream-id", default="async_cancel_01")
    ap.add_argument("--url", default="video-analyzer/data/01.mp4")
    ap.add_argument("--timeout", type=int, default=10)
    ap.add_argument("--poll-sec", type=int, default=15)
    args = ap.parse_args()

    payload = {"stream_id": args.stream_id, "profile": args.profile, "url": args.url}
    r = post_json(args.base, "/api/subscriptions", payload, args.timeout, expect_status=202)
    sub_id = (r.get("data") or {}).get("id")
    if not sub_id:
        print(f"[ERR] missing id: {r}")
        return 2

    delete_json(args.base, f"/api/subscriptions/{sub_id}", args.timeout, expect_status=202)

    # poll for cancelled
    deadline = time.time() + args.poll_sec
    cancelled = False
    while time.time() < deadline:
        st = get_json(args.base, f"/api/subscriptions/{sub_id}", args.timeout)
        sdata = st.get("data", {})
        phase = (sdata.get("phase") or "").lower()
        if phase in ("cancelled", "failed", "ready"):
            cancelled = (phase == "cancelled")
            break
        time.sleep(0.3)

    if not cancelled:
        print(f"[ERR] not cancelled: last phase={phase}")
        return 2
    print(f"[PASS] cancelled id={sub_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

