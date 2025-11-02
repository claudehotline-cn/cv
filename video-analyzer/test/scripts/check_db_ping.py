#!/usr/bin/env python3
"""Quick DB health + retention purge check.

Usage:
  python check_db_ping.py --base http://127.0.0.1:8082 --purge 0

When --purge > 0, attempts a manual purge for both logs/events with the
provided seconds value (admin/test only).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Iterable

import requests


def main(argv: Iterable[str]) -> int:
    ap = argparse.ArgumentParser(description="Check /api/db/ping and optional retention purge")
    ap.add_argument("--base", default="http://127.0.0.1:8082", help="Base URL of REST API")
    ap.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout seconds")
    ap.add_argument("--purge", type=int, default=0, help="If >0, call retention purge with given seconds")
    args = ap.parse_args(list(argv))

    base = args.base.rstrip("/")
    # 1) ping
    r = requests.get(base + "/api/db/ping", timeout=args.timeout)
    r.raise_for_status()
    j = r.json()
    ok = bool(j.get("ok"))
    print(f"[db.ping] ok={ok} payload={json.dumps(j, ensure_ascii=False)}")
    if not ok:
        return 2

    # 2) optional purge
    if args.purge > 0:
        payload = {"events_seconds": args.purge, "logs_seconds": args.purge}
        r2 = requests.post(base + "/api/db/retention/purge", json=payload, timeout=args.timeout)
        r2.raise_for_status()
        j2 = r2.json()
        print(f"[db.retention.purge] {json.dumps(j2, ensure_ascii=False)}")

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

