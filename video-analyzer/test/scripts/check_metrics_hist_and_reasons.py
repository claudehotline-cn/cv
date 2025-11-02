"""
Drive one failing subscription to populate metrics, then verify presence of
duration histograms and failed reasons aggregation.

Steps:
 1) POST /api/subscriptions with invalid model_id (allowed rtsp scheme)
 2) Poll GET until terminal (failed/ready/cancelled) or timeout
 3) GET /metrics and check for:
    - va_subscription_duration_seconds_bucket
    - va_subscription_phase_seconds_bucket{phase in opening_rtsp/loading_model/starting_pipeline}
    - va_subscriptions_failed_by_reason_total (expect at least one reason line)

Exit codes: 0 pass (presence only); 2 fail.
"""
from __future__ import annotations
import argparse
import re
import sys
import time
import requests


def post_json(base: str, path: str, payload: dict, timeout: float):
    r = requests.post(base + path, json=payload, timeout=timeout)
    return r.status_code, (r.json() if r.content else {})


def get_json(base: str, path: str, timeout: float):
    r = requests.get(base + path, timeout=timeout)
    return r.status_code, (r.json() if r.content else {})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8082')
    ap.add_argument('--timeout', type=float, default=5.0)
    ap.add_argument('--poll-sec', type=float, default=10.0)
    args = ap.parse_args()

    # 1) create a failing subscription by providing a non-existent model_id
    payload = {
        'stream_id': 'metrics_fail_01',
        'profile': 'det_720p',
        'url': 'rtsp://127.0.0.1:8554/camera_01',
        'model_id': 'nonexistent_model_id_abc'
    }
    st, body = post_json(args.base, '/api/subscriptions', payload, args.timeout)
    if st != 202:
        # One retry after a brief wait for 429/limits
        time.sleep(1.2)
        st, body = post_json(args.base, '/api/subscriptions', payload, args.timeout)
    if st != 202:
        print({'error': 'create_failed', 'status': st, 'body': str(body)[:200]})
        return 2
    sub_id = (body.get('data') or {}).get('id') or ''
    if not sub_id:
        print({'error': 'no_id_from_create', 'body': body})
        return 2

    # 2) poll terminal
    deadline = time.time() + args.poll_sec
    phase = ''
    while time.time() < deadline:
        st, js = get_json(args.base, f'/api/subscriptions/{sub_id}', args.timeout)
        if st == 200:
            phase = (js.get('data') or {}).get('phase') or ''
            p = str(phase).lower()
            if p in ('failed','ready','cancelled'):
                break
        time.sleep(0.2)

    # 3) read metrics and check presence
    ok = True
    try:
        txt = requests.get(args.base.rstrip('/') + '/metrics', timeout=args.timeout).text
    except Exception:
        print({'error': 'metrics_fetch_failed'})
        return 2

    has_total_hist = re.search(r'^va_subscription_duration_seconds_bucket\{', txt, re.M) is not None
    # accept any of the phases (opening/loading/starting) being present
    has_phase_hist = re.search(r'^va_subscription_phase_seconds_bucket\{[^}]*phase="(opening_rtsp|loading_model|starting_pipeline)"', txt, re.M) is not None
    has_failed_reason = re.search(r'^va_subscriptions_failed_by_reason_total\{', txt, re.M) is not None

    ok = has_total_hist and has_phase_hist and has_failed_reason
    summary = {
        'phase': phase,
        'has_total_hist': has_total_hist,
        'has_phase_hist': has_phase_hist,
        'has_failed_reason': has_failed_reason,
        'pass': ok,
    }
    print(summary)
    return 0 if ok else 2


if __name__ == '__main__':
    sys.exit(main())

