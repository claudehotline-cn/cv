#!/usr/bin/env python3
"""
Lightweight soak/load generator for VA REST subscriptions.
Creates subscriptions in a loop with configurable concurrency and duration.
Outputs a JSON summary at the end to stdout.

Usage:
  python soak_load.py --base http://127.0.0.1:8082 --concurrency 20 --duration-min 10 \
         --uri rtsp://127.0.0.1:8554/camera_01 --profile det_720p --api-key soak
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import random
import string
import sys
import threading
import time
from typing import Iterable

import requests


def rand_id(n: int = 6) -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))


def post_sub(base: str, profile: str, uri: str, timeout: float, headers: dict[str, str] | None) -> int:
    url = base.rstrip('/') + '/api/subscriptions?use_existing=0'
    body = {"stream_id": f"soak_{rand_id()}", "profile": profile, "source_uri": uri}
    try:
        r = requests.post(url, json=body, timeout=timeout, headers=headers or {})
        return r.status_code
    except Exception:
        return -1


def main(argv: Iterable[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--base', default='http://127.0.0.1:8082')
    p.add_argument('--concurrency', type=int, default=20)
    p.add_argument('--duration-min', type=float, default=10.0)
    p.add_argument('--uri', default='rtsp://127.0.0.1:8554/camera_01')
    p.add_argument('--profile', default='det_720p')
    p.add_argument('--timeout', type=float, default=5.0)
    p.add_argument('--api-key', default='')
    args = p.parse_args(list(argv))

    base = args.base.rstrip('/')
    headers = {"X-API-Key": args.api_key} if args.api_key else None
    # Health check
    try:
        h = requests.get(base + '/api/system/info', timeout=args.timeout)
        h.raise_for_status()
    except Exception as e:
        print(json.dumps({"error": f"health_check_failed: {e}"}))
        return 1

    stop_ts = time.time() + (args.duration_min * 60.0)
    lock = threading.Lock()
    stats = {"ok": 0, "err": 0, "r429": 0, "r403": 0, "r500": 0, "other": 0}

    def worker() -> None:
        while time.time() < stop_ts:
            code = post_sub(base, args.profile, args.uri, args.timeout, headers)
            with lock:
                if code in (200, 202):
                    stats["ok"] += 1
                elif code == 429:
                    stats["r429"] += 1
                elif code == 403:
                    stats["r403"] += 1
                elif code == 500:
                    stats["r500"] += 1
                elif code < 0:
                    stats["err"] += 1
                else:
                    stats["other"] += 1
            # small pacing to avoid busy spin
            time.sleep(0.05)

    n = max(1, int(args.concurrency))
    with futures.ThreadPoolExecutor(max_workers=n) as ex:
        futs = [ex.submit(worker) for _ in range(n)]
        for f in futs:
            f.result()

    out = {
        "base": base,
        "concurrency": n,
        "duration_min": args.duration_min,
        "profile": args.profile,
        "uri": args.uri,
        "stats": stats,
        "ts": int(time.time()*1000)
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

