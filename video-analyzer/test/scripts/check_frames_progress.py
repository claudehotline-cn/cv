"""
Polls /api/pipelines to ensure processed_frames increases after subscribe.

Usage:
  python check_frames_progress.py --base http://127.0.0.1:8082 \
      --stream camera_01 --profile det_720p \
      --url rtsp://127.0.0.1:8554/camera_01 --timeout 45 --min-frames 2
"""
from __future__ import annotations
import argparse
import time
import uuid
import sys
import requests


def get_json(base: str, path: str, timeout: int):
    r = requests.get(base + path, timeout=timeout)
    r.raise_for_status()
    return r.json()


def post_json(base: str, path: str, payload: dict, timeout: int):
    r = requests.post(base + path, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def find_pipeline(data: list[dict], key: str) -> dict | None:
    for item in data:
        if item.get("key") == key:
            return item
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8082")
    ap.add_argument("--stream", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--timeout", type=int, default=45)
    ap.add_argument("--min-frames", type=int, default=1)
    args = ap.parse_args()

    stream_id = f"{args.stream}_{uuid.uuid4().hex[:6]}"
    pipeline_key = f"{stream_id}:{args.profile}"
    print(f"[info] subscribing key={pipeline_key}")
    post_json(args.base, "/api/subscribe", {
        "stream_id": stream_id,
        "profile": args.profile,
        "url": args.url
    }, args.timeout)

    try:
        start = time.time()
        seen = 0
        last = None
        while time.time() - start < args.timeout:
            payload = get_json(args.base, "/api/pipelines", args.timeout)
            data = payload.get("data", [])
            pl = find_pipeline(data, pipeline_key)
            if not pl:
                time.sleep(1)
                continue
            metrics = pl.get("metrics", {})
            frames = int(metrics.get("processed_frames", 0))
            fps = float(metrics.get("fps", 0.0))
            print(f"  frames={frames} fps={fps:.2f}")
            if last is None:
                last = frames
            if frames > last:
                seen += (frames - last)
                last = frames
            if seen >= args.min_frames:
                print("[PASS] frames progressed")
                return 0
            time.sleep(1)
        print("[FAIL] frames did not progress enough within timeout")
        return 2
    finally:
        try:
            post_json(args.base, "/api/unsubscribe", {
                "stream_id": stream_id,
                "profile": args.profile
            }, args.timeout)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())

