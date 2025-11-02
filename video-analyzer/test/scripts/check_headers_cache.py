#!/usr/bin/env python3
"""
验证 /api/subscriptions 的响应头与缓存语义：
- POST 返回 202 且包含 Location 头
- GET 返回 ETag；带 If-None-Match 命中 304
- （可选）尝试触发 429 并校验 Retry-After（若未触发则 WARN，不判失败）

用法：
  python check_headers_cache.py --base http://127.0.0.1:8082 --timeout 5
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import sys
from typing import Iterable

import requests


def post_sub(base: str, stream: str, profile: str, uri: str, timeout: float) -> requests.Response:
    url = base.rstrip('/') + '/api/subscriptions?use_existing=0'
    body = {"stream_id": stream, "profile": profile, "source_uri": uri}
    r = requests.post(url, json=body, timeout=timeout)
    return r


def main(argv: Iterable[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--base', default='http://127.0.0.1:8082')
    p.add_argument('--timeout', type=float, default=5.0)
    p.add_argument('--uri', default='rtsp://127.0.0.1:8554/camera_01')
    args = p.parse_args(list(argv))

    base = args.base.rstrip('/')
    # 1) POST -> 202 + Location
    r = post_sub(base, 'hdrs_cache', 'det_720p', args.uri, args.timeout)
    if r.status_code != 202:
        print(f'[FAIL] POST expected 202, got {r.status_code}')
        return 1
    location = r.headers.get('Location', '')
    if not location:
        print('[FAIL] POST missing Location header')
        return 1
    sub_url = base + location
    # 2) GET -> ETag；再 If-None-Match -> 304
    g = requests.get(sub_url, timeout=args.timeout)
    if g.status_code != 200:
        print(f'[FAIL] GET expected 200, got {g.status_code}')
        return 1
    etag = g.headers.get('ETag', '')
    if not etag:
        print('[FAIL] GET missing ETag header')
        return 1
    g2 = requests.get(sub_url, headers={'If-None-Match': etag}, timeout=args.timeout)
    if g2.status_code != 304:
        print(f'[FAIL] Conditional GET expected 304, got {g2.status_code}')
        return 1

    # 3) 429 + Retry-After（尽力而为）：并发轰击队列
    got_429 = False
    with futures.ThreadPoolExecutor(max_workers=64) as ex:
        futs = [ex.submit(post_sub, base, f'qq{i}', 'det_720p', args.uri, args.timeout) for i in range(256)]
        for f in futs:
            try:
                rr = f.result()
                if rr.status_code == 429:
                    ra = rr.headers.get('Retry-After', '')
                    if not ra:
                        print('[FAIL] 429 missing Retry-After header')
                        return 1
                    got_429 = True
                    break
            except Exception:
                pass
    if not got_429:
        print('[WARN] 429 not observed (queue not saturated); skipping Retry-After check')

    print('[OK] headers + cache semantics verified')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

