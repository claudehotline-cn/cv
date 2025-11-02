#!/usr/bin/env python3
"""Check /api/db/retention/status endpoint.

Usage:
  python check_retention_status.py --base http://127.0.0.1:8082
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Iterable

import requests


def main(argv: Iterable[str]) -> int:
    ap = argparse.ArgumentParser(description="Check /api/db/retention/status")
    ap.add_argument("--base", default="http://127.0.0.1:8082", help="Base URL of REST API")
    ap.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout seconds")
    args = ap.parse_args(list(argv))

    base = args.base.rstrip("/")
    r = requests.get(base + "/api/db/retention/status", timeout=args.timeout)
    r.raise_for_status()
    j = r.json()
    d = j.get("data", j)
    cfg = d.get("config", {})
    m = d.get("metrics", {})

    assert isinstance(cfg, dict) and "enabled" in cfg, "config.enabled missing"
    assert isinstance(m, dict) and "runs_total" in m, "metrics.runs_total missing"

    print(json.dumps({
        "ok": True,
        "config": cfg,
        "metrics": m
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

