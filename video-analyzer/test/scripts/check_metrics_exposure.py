#!/usr/bin/env python3
"""
检查 /metrics 是否包含订阅相关的关键指标，并做最小断言。

用法:
    python scripts/check_metrics_exposure.py --base http://127.0.0.1:8082

退出码: 全部通过返回 0，任一缺失返回 1。
"""
from __future__ import annotations

import argparse
import sys
from typing import Iterable

import requests


BASE_REQUIRED = [
    # 基本态
    "va_subscriptions_queue_length",
    "va_subscriptions_in_progress",
    "va_subscriptions_states",
    "va_subscriptions_completed_total",
    # 直方图（总时长）
    "va_subscription_duration_seconds_bucket",
    "va_subscription_duration_seconds_sum",
    "va_subscription_duration_seconds_count",
]

OPTIONAL_PHASE = [
    "va_subscription_phase_seconds_bucket",
    "va_subscription_phase_seconds_sum",
    "va_subscription_phase_seconds_count",
]


def main(argv: Iterable[str]) -> int:
    p = argparse.ArgumentParser(description="Check /metrics exposure for subscription metrics")
    p.add_argument("--base", default="http://127.0.0.1:8082", help="Base URL of VA (default: http://127.0.0.1:8082)")
    p.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout in seconds (default: 5.0)")
    args = p.parse_args(list(argv))

    url = args.base.rstrip("/") + "/metrics"
    r = requests.get(url, timeout=args.timeout)
    r.raise_for_status()
    text = r.text or ""
    missing = [m for m in BASE_REQUIRED if m not in text]
    if missing:
        print("[FAIL] missing metrics:", ", ".join(missing))
        return 1

    # 额外健壮性：至少一个总时长 bucket 行
    ok_bucket = any(line.startswith("va_subscription_duration_seconds_bucket") for line in text.splitlines())
    if not ok_bucket:
        print("[FAIL] duration histogram buckets not found")
        return 1

    # 分阶段直方图可选：缺失时输出提醒但不判失败
    ph_missing = [m for m in OPTIONAL_PHASE if m not in text]
    if ph_missing:
        print("[WARN] phase histogram missing (acceptable for now)")
    else:
        print("[OK] phase histogram present")

    print("[OK] metrics exposure looks good (base)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
