#!/usr/bin/env python3
"""
检查 /api/system/info 中 subscriptions.fair_window 字段是否存在且为整数。

用法:
    python check_fair_window_info.py --base http://127.0.0.1:8082 --timeout 5.0

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

    url = args.base.rstrip('/') + '/api/system/info'
    r = requests.get(url, timeout=args.timeout)
    r.raise_for_status()
    js = r.json()
    try:
        fw = js['data']['subscriptions']['fair_window']
    except Exception:
        print('[FAIL] subscriptions.fair_window missing')
        return 1
    if not isinstance(fw, int):
        print('[FAIL] fair_window not int:', type(fw))
        return 1
    print('[OK] subscriptions.fair_window =', fw)
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

