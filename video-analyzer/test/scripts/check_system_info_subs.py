"""
Verify /api/system/info subscriptions snapshot and source echo.

Checks:
- data.subscriptions exists with keys: heavy_slots, model_slots, rtsp_slots,
  open_rtsp_slots, start_pipeline_slots, max_queue, ttl_seconds (types: int/number).
- data.subscriptions.source exists with the same keys, values in {"defaults","config","env"}.

Exit codes: 0 pass; 2 fail.
"""
from __future__ import annotations
import argparse
import sys
import requests


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8082')
    ap.add_argument('--timeout', type=float, default=5.0)
    args = ap.parse_args()

    r = requests.get(args.base.rstrip('/') + '/api/system/info', timeout=args.timeout)
    r.raise_for_status()
    js = r.json()
    data = js.get('data') or {}
    subs = data.get('subscriptions') or {}
    src = subs.get('source') or {}
    keys = ['heavy_slots','model_slots','rtsp_slots','open_rtsp_slots','start_pipeline_slots','max_queue','ttl_seconds']
    ok = True
    miss = []
    badt = []
    badsrc = []
    for k in keys:
        if k not in subs:
            ok = False; miss.append(k); continue
        v = subs[k]
        if not isinstance(v, (int, float)):
            ok = False; badt.append(k)
        if k not in src:
            ok = False; badsrc.append(k); continue
        s = src[k]
        if not isinstance(s, str) or s not in ('defaults','config','env'):
            ok = False; badsrc.append(k)
    summary = {
        'missing': miss,
        'bad_types': badt,
        'bad_source': badsrc,
        'pass': ok
    }
    print(summary)
    return 0 if ok else 2


if __name__ == '__main__':
    sys.exit(main())

