"""
Single-mode pipeline validation with readiness waits and retries.

Usage:
  python check_single_mode.py --base http://127.0.0.1:8082 \
      --engine ort-cpu \
      --profile det_720p \
      --url video-analyzer/data/01.mp4 \
      --duration-sec 12 --warmup-sec 2 --timeout 10 \
      [--opts key1=true key2=123]
Exit codes: 0 on success (frames>0), 2 on failure.
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


def wait_ready(base: str, timeout: int, max_wait: int = 8) -> bool:
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


def set_engine(base: str, engine: str, opts: dict, timeout: int) -> None:
    payload = {
        "type": engine,
        "device": 0,
        "options": {k: ("true" if v is True else "false" if v is False else v) for k, v in opts.items()},
    }
    last = None
    for _ in range(4):
        try:
            post_json(base, "/api/engine/set", payload, timeout)
            return
        except Exception as e:
            last = e
            time.sleep(0.6)
            wait_ready(base, timeout, max_wait=3)
    raise last


def unsubscribe(base: str, stream_id: str, profile: str, timeout: int):
    try:
        post_json(base, "/api/unsubscribe", {"stream_id": stream_id, "profile": profile}, timeout)
    except Exception:
        pass


def parse_opts(opts_list: list[str]) -> dict:
    out = {}
    for item in opts_list:
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        v_low = v.lower()
        if v_low in ("true", "1", "yes", "on"):
            out[k] = True
        elif v_low in ("false", "0", "no", "off"):
            out[k] = False
        else:
            out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8082")
    ap.add_argument("--engine", default="ort-cpu")
    ap.add_argument("--no-set-engine", action="store_true")
    ap.add_argument("--profile", default="det_720p")
    ap.add_argument("--url", required=True)
    ap.add_argument("--duration-sec", type=int, default=12)
    ap.add_argument("--warmup-sec", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=10)
    ap.add_argument("--opts", nargs="*", default=[])
    args = ap.parse_args()

    opts = parse_opts(args.opts)

    # readiness and engine set (optional)
    wait_ready(args.base, args.timeout, max_wait=8)
    if not args.no_set_engine:
        try:
            set_engine(args.base, args.engine, opts, args.timeout)
        except Exception as e:
            print(f"[ERR] set_engine failed: {e}")
            return 2
        if not wait_ready(args.base, args.timeout, max_wait=8):
            print("[ERR] backend not ready after engine set")
            return 2

    stream_id = f"single_{uuid.uuid4().hex[:6]}"
    key = f"{stream_id}:{args.profile}"
    # subscribe with retries (backend may briefly restart after engine set)
    sub_payload = {"stream_id": stream_id, "profile": args.profile, "url": args.url}
    last = None
    ok_sub = False
    for _ in range(6):
        try:
            post_json(args.base, "/api/subscribe", sub_payload, args.timeout)
            ok_sub = True
            break
        except Exception as e:
            last = e
            time.sleep(1.0)
            wait_ready(args.base, args.timeout, max_wait=4)
    if not ok_sub:
        print(f"[ERR] subscribe failed: {last}")
        return 2

    try:
        time.sleep(args.warmup_sec)
        start = time.time()
        last_frames = None
        frames_gained = 0
        while time.time() - start < args.duration_sec:
            try:
                data = get_json(args.base, "/api/pipelines", args.timeout).get("data", [])
                pl = next((p for p in data if p.get("key") == key), None)
                if pl:
                    m = pl.get("metrics", {})
                    frames = int(m.get("processed_frames", 0))
                    fps = float(m.get("fps", 0.0))
                    print(f"frames={frames} fps={fps:.2f}")
                    if last_frames is None:
                        last_frames = frames
                    elif frames > last_frames:
                        frames_gained += (frames - last_frames)
                        last_frames = frames
            except Exception:
                pass
            time.sleep(1)
        if frames_gained > 0:
            print(f"[PASS] frames gained: {frames_gained}")
            return 0
        print("[FAIL] no frames gained")
        return 2
    finally:
        unsubscribe(args.base, stream_id, args.profile, args.timeout)


if __name__ == "__main__":
    sys.exit(main())
