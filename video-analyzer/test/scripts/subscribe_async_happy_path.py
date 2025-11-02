"""
Async subscription happy path test.

Steps:
 1) POST /api/subscriptions to create a subscription
 2) Poll GET /api/subscriptions/{id} until phase=ready (or timeout)
 3) Verify pipeline exists in /api/pipelines and processed frames increase
 4) DELETE /api/subscriptions/{id} to cancel/cleanup

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


def wait_backend_ready(base: str, timeout: int, max_wait: int = 8) -> bool:
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            r = requests.get(base + "/api/system/info", timeout=timeout)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8082")
    ap.add_argument("--profile", default="det_720p")
    ap.add_argument("--stream-id", default="async_test_01")
    ap.add_argument("--url", default="video-analyzer/data/01.mp4")
    ap.add_argument("--timeout", type=int, default=10)
    ap.add_argument("--wait-ready-sec", type=int, default=20)
    ap.add_argument("--poll-sec", type=int, default=30)
    args = ap.parse_args()

    if not wait_backend_ready(args.base, args.timeout, max_wait=args.wait_ready_sec):
        print("[ERR] backend not ready")
        return 2

    sub_payload = {"stream_id": args.stream_id, "profile": args.profile, "url": args.url}
    data = post_json(args.base, "/api/subscriptions", sub_payload, args.timeout, expect_status=202)
    sub_id = (data.get("data") or {}).get("id")
    if not sub_id:
        print(f"[ERR] missing subscription id in response: {data}")
        return 2

    # poll status
    deadline = time.time() + args.poll_sec
    ready = False
    while time.time() < deadline:
        st = get_json(args.base, f"/api/subscriptions/{sub_id}", args.timeout)
        sdata = st.get("data", {})
        phase = (sdata.get("phase") or "").lower()
        if phase in ("ready", "failed", "cancelled"):
            ready = (phase == "ready")
            reason = sdata.get("reason")
            if not ready:
                print(f"[ERR] subscription finished with phase={phase}, reason={reason}")
            break
        time.sleep(0.5)

    if not ready:
        return 2

    key = f"{args.stream_id}:{args.profile}"
    # observe frames increase for a few seconds
    last = None
    gained = 0
    start = time.time()
    while time.time() - start < 6:
        try:
            plist = get_json(args.base, "/api/pipelines", args.timeout).get("data", [])
            pl = next((p for p in plist if p.get("key") == key), None)
            if pl:
                m = pl.get("metrics", {})
                frames = int(m.get("processed_frames", 0))
                if last is not None and frames > last:
                    gained += (frames - last)
                last = frames
        except Exception:
            pass
        time.sleep(1.0)

    if gained <= 0:
        print("[ERR] no frames gained after ready")
        # still cleanup
        try:
            delete_json(args.base, f"/api/subscriptions/{sub_id}", args.timeout, expect_status=202)
        except Exception:
            pass
        return 2

    # cleanup
    delete_json(args.base, f"/api/subscriptions/{sub_id}", args.timeout, expect_status=202)
    print(f"[PASS] subscription {sub_id} ready; frames gained={gained}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

