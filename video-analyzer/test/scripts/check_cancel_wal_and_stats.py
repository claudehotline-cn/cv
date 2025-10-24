#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from typing import Iterable, Optional

import requests


def metric_value(text: str, name: str, labels: Optional[dict[str, str]] = None) -> Optional[int]:
    pat = re.escape(name)
    if labels:
        parts = [f'{k}="{v}"' for k, v in labels.items()]
        lab = '{' + ','.join(parts) + '}'
        pat += re.escape(lab)
    else:
        pat += r"\{}"
    m = re.search(pat + r"\s+(\d+)(?:\n|$)", text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def get_metrics(base: str, timeout: float) -> str:
    r = requests.get(base.rstrip('/') + '/metrics', timeout=timeout)
    r.raise_for_status()
    return r.text


def main(argv: Iterable[str]) -> int:
    p = argparse.ArgumentParser(description='Verify cancelled subscriptions are recorded in metrics and WAL (if enabled).')
    p.add_argument('--base', default='http://127.0.0.1:8082')
    p.add_argument('--timeout', type=float, default=5.0)
    p.add_argument('--uri', default='rtsp://127.0.0.1:8554/camera_01')
    p.add_argument('--profile', default='det_720p')
    args = p.parse_args(list(argv))

    base = args.base.rstrip('/')

    # Baseline metrics
    text0 = get_metrics(base, args.timeout)
    base_cancel = metric_value(text0, 'va_subscriptions_completed_total', {'result': 'cancelled'}) or 0

    # Create subscription (POST /api/subscriptions)
    url = base + '/api/subscriptions?use_existing=0'
    body = {"stream_id": f"cancel_test_{int(time.time()*1000)}", "profile": args.profile, "source_uri": args.uri}
    sid = None
    for _ in range(5):
        r = requests.post(url, json=body, timeout=args.timeout)
        if r.status_code in (200, 202):
            loc = r.headers.get('Location', '')
            if loc:
                sid = loc.rsplit('/', 1)[-1]
            else:
                try:
                    j = r.json(); sid = j.get('data', {}).get('id')
                except Exception:
                    sid = None
            break
        elif r.status_code == 429:
            ra = int(r.headers.get('Retry-After', '1') or '1')
            time.sleep(min(max(ra, 1), 5))
            continue
        else:
            raise RuntimeError(f'create failed: {r.status_code} {r.text[:200]}')
    if not sid:
        raise RuntimeError('subscription id missing')

    # Cancel: DELETE /api/subscriptions/{id}
    dr = requests.delete(base + f'/api/subscriptions/{sid}', timeout=args.timeout)
    if dr.status_code not in (200, 202):
        raise RuntimeError(f'delete failed: {dr.status_code} {dr.text[:200]}')

    # Poll phase until Cancelled (or timeout)
    ok = False
    for _ in range(20):
        gr = requests.get(base + f'/api/subscriptions/{sid}', timeout=args.timeout)
        if gr.status_code == 200:
            try:
                j = gr.json(); ph = (j.get('data') or j).get('phase', '').lower()
                if ph == 'cancelled':
                    ok = True
                    break
            except Exception:
                pass
        time.sleep(0.25)
    if not ok:
        time.sleep(0.5)

    # Metrics delta
    text1 = get_metrics(base, args.timeout)
    now_cancel = metric_value(text1, 'va_subscriptions_completed_total', {'result': 'cancelled'}) or 0
    if now_cancel < base_cancel + 1:
        raise RuntimeError(f'cancel counter not increased: before={base_cancel}, after={now_cancel}')

    # WAL (optional)
    try:
        s = requests.get(base + '/api/admin/wal/summary', timeout=args.timeout).json()
        if (s.get('data') or {}).get('enabled'):
            t = requests.get(base + '/api/admin/wal/tail?n=200', timeout=args.timeout).json()
            items = (t.get('data') or {}).get('items', [])
            base_key = body['stream_id'] + ':' + args.profile
            found = False
            for line in items:
                try:
                    obj = json.loads(line)
                    if obj.get('op') == 'cancelled' and obj.get('base_key') == base_key:
                        found = True
                        break
                except Exception:
                    continue
            if not found:
                raise RuntimeError('WAL tail missing cancelled event for base_key=' + base_key)
    except Exception as e:
        try:
            if not s.get('data', {}).get('enabled'):
                pass
            else:
                raise
        except Exception:
            raise e

    print('cancel-wal-stats: OK')
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv[1:]))

