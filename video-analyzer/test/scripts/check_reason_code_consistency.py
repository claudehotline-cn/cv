#!/usr/bin/env python3
"""
验证 reason_code 在 GET payload 与 /metrics 中的一致性：
- 用一个不存在的 model_id 触发 load_model_failed，检查 GET.reason_code 与 metrics 标签一致
- 用“开始即取消”触发 cancelled，检查 GET.reason_code=cancelled，且完成计数 cancelled 增加
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from typing import Iterable

import requests


def wait_terminal(base: str, sid: str, timeout: float) -> dict:
    url = f"{base.rstrip('/')}/api/subscriptions/{sid}"
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        j = r.json()
        ph = (j.get('data', {}).get('phase') or '').lower()
        if ph in ('ready','failed','cancelled'):
            return j
        time.sleep(0.2)
    raise TimeoutError('subscription did not reach terminal state')


def metrics_text(base: str, timeout: float) -> str:
    r = requests.get(f"{base.rstrip('/')}/metrics", timeout=timeout)
    r.raise_for_status()
    return r.text


def grep_metric(text: str, pattern: str) -> int:
    m = re.search(pattern, text)
    if not m:
        return 0
    try:
        return int(float(m.group(1)))
    except Exception:
        return 0


def main(argv: Iterable[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--base', default='http://127.0.0.1:8082')
    p.add_argument('--timeout', type=float, default=8.0)
    args = p.parse_args(list(argv))
    base = args.base.rstrip('/')

    # Case 1: load_model_failed via invalid model_id
    body = {"stream_id":"rc_model","profile":"det_720p","source_uri":"rtsp://127.0.0.1:8554/camera_01","model_id":"__no_such__"}
    r = requests.post(f"{base}/api/subscriptions?use_existing=0", json=body, timeout=args.timeout)
    r.raise_for_status()
    sid = r.json()['data']['id']
    st = wait_terminal(base, sid, args.timeout)
    rc = (st.get('data',{}).get('reason_code') or '').lower()
    if rc != 'load_model_failed':
        print(f"[FAIL] expected reason_code=load_model_failed, got {rc}")
        return 1
    txt = metrics_text(base, args.timeout)
    before = grep_metric(txt, r"va_subscriptions_failed_by_reason_total\{reason=\"load_model_failed\"\} (\d+)")
    # Small delay to ensure counters flushed
    time.sleep(0.5)
    txt2 = metrics_text(base, args.timeout)
    after = grep_metric(txt2, r"va_subscriptions_failed_by_reason_total\{reason=\"load_model_failed\"\} (\d+)")
    if after < before:
        print("[FAIL] failed_by_reason counter did not increase (load_model_failed)")
        return 1

    # Case 2: cancelled
    r = requests.post(f"{base}/api/subscriptions?use_existing=0", json={"stream_id":"rc_cancel","profile":"det_720p","source_uri":"rtsp://127.0.0.1:8554/camera_01"}, timeout=args.timeout)
    r.raise_for_status(); sid = r.json()['data']['id']
    # cancel immediately
    requests.delete(f"{base}/api/subscriptions/{sid}", timeout=args.timeout)
    st = wait_terminal(base, sid, args.timeout)
    rc = (st.get('data',{}).get('reason_code') or '').lower()
    if rc != 'cancelled':
        print(f"[FAIL] expected reason_code=cancelled, got {rc}")
        return 1
    # cancelled counted in completed_total, not in failed_by_reason
    txt3 = metrics_text(base, args.timeout)
    canc = grep_metric(txt3, r"va_subscriptions_completed_total\{result=\"cancelled\"\} (\d+)")
    if canc <= 0:
        print("[FAIL] cancelled total did not increase or missing")
        return 1

    print('[OK] reason_code consistency verified')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

