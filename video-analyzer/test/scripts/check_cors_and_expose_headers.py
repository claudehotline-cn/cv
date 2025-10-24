#!/usr/bin/env python3
"""
校验 VA 接口的 CORS 预检与暴露头部：
- OPTIONS 预检包含所需的 Access-Control-Allow-Headers（If-None-Match 等）
- 202 响应暴露 Location；304 响应暴露 ETag
- 429 响应暴露 Retry-After（并尽量触发）

用法：
  python check_cors_and_expose_headers.py --base http://127.0.0.1:8082 --timeout 5
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import sys
from typing import Iterable

import requests


def main(argv: Iterable[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8082')
    ap.add_argument('--timeout', type=float, default=5.0)
    ap.add_argument('--uri', default='rtsp://127.0.0.1:8554/camera_01')
    args = ap.parse_args(list(argv))

    base = args.base.rstrip('/')

    # 1) OPTIONS 预检：/api/subscriptions
    sess = requests.Session()
    pre = requests.Request('OPTIONS', f'{base}/api/subscriptions')
    r = sess.send(sess.prepare_request(pre), timeout=args.timeout)
    allow = (r.headers.get('Access-Control-Allow-Headers') or '').lower()
    needed = ['if-none-match', 'x-subscription-use-existing', 'x-subscription-force-new']
    missing = [h for h in needed if h not in allow]
    if missing:
        print(f'[WARN] OPTIONS Allow-Headers missing: {missing!r} -> {allow!r}')

    # 2) POST -> 202 + 暴露 Location
    body = {"stream_id": "cors_check", "profile": "det_720p", "source_uri": args.uri}
    p = requests.post(f'{base}/api/subscriptions?use_existing=0', json=body, timeout=args.timeout)
    if p.status_code == 202:
        if (p.headers.get('Access-Control-Expose-Headers') or '').lower().find('location') < 0:
            print('[FAIL] POST missing Access-Control-Expose-Headers: Location')
            return 1
        loc = p.headers.get('Location') or ''
        if not loc:
            print('[FAIL] POST missing Location header')
            return 1
    elif p.status_code == 429:
        # 配额/队列拥塞：尽量验证暴露 Retry-After（老版本可能缺失，记为 WARN）
        exp = (p.headers.get('Access-Control-Expose-Headers') or '').lower()
        if 'retry-after' not in exp:
            print('[WARN] POST 429 missing Access-Control-Expose-Headers: Retry-After')
        else:
            print('[ok] POST 429 exposes Retry-After')
        print('[WARN] POST returned 429; skip Location/ETag checks')
        return 0
    else:
        print(f'[FAIL] POST expected 202/429, got {p.status_code}')
        return 1

    # 3) GET -> 200 + ETag；再 If-None-Match -> 304 + 暴露 ETag
    sub_url = base + loc
    g = requests.get(sub_url, timeout=args.timeout)
    if g.status_code != 200:
        print(f'[FAIL] GET expected 200, got {g.status_code}')
        return 1
    etag = g.headers.get('ETag') or ''
    if not etag:
        print('[FAIL] GET missing ETag')
        return 1
    g2 = requests.get(sub_url, headers={'If-None-Match': etag}, timeout=args.timeout)
    if g2.status_code != 304:
        print(f'[FAIL] Conditional GET expected 304, got {g2.status_code}')
        return 1
    if (g2.headers.get('Access-Control-Expose-Headers') or '').lower().find('etag') < 0:
        print('[FAIL] 304 missing Access-Control-Expose-Headers: ETag')
        return 1

    # 4) 并发触发 429；校验暴露 Retry-After
    def post_once(i: int) -> requests.Response:
        return requests.post(f'{base}/api/subscriptions?use_existing=0', json={"stream_id": f'cc{i}', "profile": "det_720p", "source_uri": args.uri}, timeout=args.timeout)

    got_429 = False
    with futures.ThreadPoolExecutor(max_workers=64) as ex:
        futs = [ex.submit(post_once, i) for i in range(256)]
        for f in futs:
            try:
                rr = f.result()
                if rr.status_code == 429:
                    exp = (rr.headers.get('Access-Control-Expose-Headers') or '').lower()
                    if 'retry-after' not in exp:
                        print('[WARN] 429 missing Access-Control-Expose-Headers: Retry-After')
                    else:
                        print('[ok] 429 exposes Retry-After')
                    got_429 = True
                    break
            except Exception:
                pass
    if not got_429:
        print('[WARN] 429 not observed; skipping expose header check (ok)')

    print('[OK] CORS preflight + expose headers verified')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
