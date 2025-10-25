#!/usr/bin/env python3
"""
检查 /metrics 是否暴露 va_subscriptions_fair_window 指标（gauge）。

用法:
    python check_fair_window_metric.py --base http://127.0.0.1:8082 --timeout 5.0

返回码: 成功=0，失败=1
"""
from __future__ import annotations
import argparse, sys
import requests

def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument('--base', default='http://127.0.0.1:8082')
    p.add_argument('--timeout', type=float, default=5.0)
    args = p.parse_args(argv)

    url = args.base.rstrip('/') + '/metrics'
    r = requests.get(url, timeout=args.timeout)
    r.raise_for_status()
    txt = r.text or ''
    if 'va_subscriptions_fair_window' not in txt:
        print('[FAIL] fair_window metric missing')
        return 1
    print('[OK] fair_window metric present')
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

