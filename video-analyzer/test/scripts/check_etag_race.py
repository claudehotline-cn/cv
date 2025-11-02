#!/usr/bin/env python3
"""
并发场景下的 ETag/If-None-Match 竞态校验：
- 创建订阅，获取 Location。
- 并发反复 GET /api/subscriptions/{id}，携带最近一次收到的 ETag 作为 If-None-Match。
- 断言：当返回 200 时，返回的 ETag 必须与请求的 If-None-Match 不同；当相同则应返回 304。

用法：
  python check_etag_race.py --base http://127.0.0.1:8082 --uri rtsp://127.0.0.1:8554/camera_01
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import time
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
    p.add_argument('--threads', type=int, default=8)
    p.add_argument('--loops', type=int, default=20)
    args = p.parse_args(list(argv))

    base = args.base.rstrip('/')
    # 1) 创建订阅
    r = post_sub(base, 'etag_race', 'det_720p', args.uri, args.timeout)
    if r.status_code not in (200, 202):
        print(f'[FAIL] POST expected 200/202, got {r.status_code}')
        return 1
    location = r.headers.get('Location', '')
    if not location:
        # 某些情况下可能直接 200 返回 data.id，此处做兼容
        try:
            j = r.json(); sid = j.get('data', {}).get('id', '')
            if not sid:
                print('[FAIL] missing Location and id')
                return 1
            sub_url = f"{base}/api/subscriptions/{sid}"
        except Exception:
            print('[FAIL] missing Location and invalid body')
            return 1
    else:
        sub_url = base + location

    # 2) 初次 GET，拿到首个 ETag
    g0 = requests.get(sub_url, timeout=args.timeout)
    if g0.status_code != 200:
        print(f'[FAIL] initial GET expected 200, got {g0.status_code}')
        return 1
    etag0 = g0.headers.get('ETag', '')
    if not etag0:
        print('[FAIL] initial GET missing ETag header')
        return 1

    # 3) 并发循环 GET
    def worker(idx: int) -> int:
        last = etag0
        session = requests.Session()
        for i in range(args.loops):
            h = {'If-None-Match': last}
            try:
                r = session.get(sub_url, headers=h, timeout=args.timeout)
            except Exception:
                # 短暂异常容忍：重试下一轮
                time.sleep(0.05)
                continue
            if r.status_code == 304:
                # 未变化，OK
                time.sleep(0.01)
                continue
            if r.status_code != 200:
                # 订阅可能终态或偶发错误，放宽为重试
                time.sleep(0.02)
                continue
            et = r.headers.get('ETag', '')
            if not et:
                print(f'[FAIL] 200 without ETag (thread {idx})')
                return 1
            # 若返回 200，则 ETag 必须变化
            if et == last:
                print(f'[FAIL] 200 but ETag unchanged (thread {idx})')
                return 1
            last = et
            time.sleep(0.01)
        return 0

    ok = True
    with futures.ThreadPoolExecutor(max_workers=args.threads) as ex:
        futs = [ex.submit(worker, i) for i in range(args.threads)]
        for f in futs:
            rc = f.result()
            if rc != 0:
                ok = False
    if not ok:
        return 1
    print('[OK] etag race verified')
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv[1:]))

