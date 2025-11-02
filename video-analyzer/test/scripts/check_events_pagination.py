#!/usr/bin/env python3
"""Check /api/events/recent pagination with time window.

Usage:
  python check_events_pagination.py --base http://127.0.0.1:8082 --mins 30
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Iterable

import requests


def main(argv: Iterable[str]) -> int:
    ap = argparse.ArgumentParser(description="Check /api/events/recent pagination")
    ap.add_argument("--base", default="http://127.0.0.1:8082", help="Base URL of REST API")
    ap.add_argument("--timeout", type=float, default=8.0, help="HTTP timeout seconds")
    ap.add_argument("--mins", type=int, default=30, help="Time window minutes (from now)")
    ap.add_argument("--page", type=int, default=1, help="Page number")
    ap.add_argument("--page_size", type=int, default=50, help="Page size")
    args = ap.parse_args(list(argv))

    base = args.base.rstrip("/")
    now = int(time.time() * 1000)
    frm = now - max(1, args.mins) * 60 * 1000

    url = f"{base}/api/events/recent?from_ts={frm}&to_ts={now}&page={args.page}&page_size={args.page_size}"
    r = requests.get(url, timeout=args.timeout)
    r.raise_for_status()
    j = r.json()
    d = j.get("data", j)
    items = d.get("items", [])
    total = int(d.get("total", len(items)))

    assert isinstance(items, list), "items must be a list"
    assert total >= 0, "total must be >= 0"

    print(json.dumps({
        "ok": True,
        "count": len(items),
        "total": total,
        "first": (items[0] if items else None)
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

