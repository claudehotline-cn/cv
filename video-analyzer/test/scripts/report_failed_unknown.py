"""
Report unknown ratio for failed reasons from Prometheus metrics, and try to
derive Top-10 original error keywords from available logs (best-effort).

Outputs a compact JSON summary to stdout. Does not require frontend.

Fields:
{
  "total_failed": int,
  "unknown": int,
  "unknown_ratio": float,           # 0..1
  "reasons_top": [[reason, count], ...],
  "orig_keywords_top": [[word, count], ...],
  "sources": {"metrics": bool, "logs_api": bool, "stderr": bool}
}

Note: If logs API or stderr files are unavailable, orig_keywords_top may be empty.
"""
from __future__ import annotations
import argparse
import collections
import json
import os
import re
import sys
from typing import Dict, List, Tuple

import requests


def fetch_metrics(base: str, timeout: float) -> str:
    r = requests.get(base.rstrip('/') + '/metrics', timeout=timeout)
    r.raise_for_status()
    return r.text


def parse_failed_by_reason(metrics_text: str) -> Dict[str, int]:
    # Expect lines like: va_subscriptions_failed_by_reason_total{reason="load_model_failed"} 12
    counts: Dict[str, int] = {}
    pat = re.compile(r'^va_subscriptions_failed_by_reason_total\{[^}]*reason="([^"]+)"[^}]*\}\s+(\d+(?:\.\d+)?)\s*$', re.M)
    for m in pat.finditer(metrics_text):
        reason = m.group(1)
        val = m.group(2)
        try:
            n = int(float(val))
        except Exception:
            n = 0
        counts[reason] = counts.get(reason, 0) + n
    return counts


def fetch_logs_api(base: str, timeout: float, limit: int = 500) -> List[str]:
    url = base.rstrip('/') + '/api/logs?limit=%d' % limit
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code != 200:
            return []
        js = r.json()
        items = (js.get('items') or js.get('data', {}).get('items') or [])
        msgs = []
        for it in items:
            msg = ''
            if isinstance(it, dict):
                msg = it.get('message') or it.get('msg') or ''
            if msg:
                msgs.append(str(msg))
        return msgs
    except Exception:
        return []


def read_stderr_files() -> List[str]:
    # Try a few common files near the binary output dir
    candidates = [
        os.path.join('video-analyzer', 'build-ninja', 'bin', 'va.err'),
        os.path.join('video-analyzer', 'build-ninja', 'bin', 'va.out'),
    ]
    msgs: List[str] = []
    for p in candidates:
        try:
            if os.path.isfile(p):
                with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                    txt = f.read()
                if txt:
                    msgs.extend([line.strip() for line in txt.splitlines() if line.strip()])
        except Exception:
            pass
    return msgs


def extract_keywords(messages: List[str], topn: int = 10) -> List[Tuple[str, int]]:
    if not messages:
        return []
    # Simple tokenization: lower, remove non-letters/digits/underscore, split by spaces
    freq: Dict[str, int] = collections.Counter()
    for msg in messages:
        s = msg.lower()
        s = re.sub(r'[^a-z0-9_\-\.\: ]+', ' ', s)
        tokens = [t for t in s.split() if len(t) >= 3 and not t.isdigit()]
        for t in tokens:
            freq[t] += 1
    # Filter extremely generic tokens
    stop = set(['failed', 'error', 'warn', 'subscribe', 'switch', 'model', 'task', 'rtsp', 'open', 'load', 'pipeline', 'timeout'])
    items = [(w, c) for w, c in freq.items() if w not in stop]
    items.sort(key=lambda x: x[1], reverse=True)
    return items[:topn]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8082')
    ap.add_argument('--timeout', type=float, default=5.0)
    ap.add_argument('--top', type=int, default=10)
    args = ap.parse_args()

    metrics_text = ''
    reasons: Dict[str, int] = {}
    try:
        metrics_text = fetch_metrics(args.base, args.timeout)
        reasons = parse_failed_by_reason(metrics_text)
    except Exception:
        reasons = {}

    total_failed = sum(reasons.values())
    unknown = reasons.get('unknown', 0)
    unknown_ratio = (float(unknown) / total_failed) if total_failed > 0 else 0.0
    reasons_top = sorted(reasons.items(), key=lambda x: x[1], reverse=True)[:args.top]

    # Try logs sources for original messages (best-effort)
    msgs_api = fetch_logs_api(args.base, args.timeout, limit=1000)
    msgs_err = read_stderr_files()
    keywords = extract_keywords(msgs_api + msgs_err, topn=args.top)

    out = {
        'total_failed': total_failed,
        'unknown': unknown,
        'unknown_ratio': round(unknown_ratio, 6),
        'reasons_top': reasons_top,
        'orig_keywords_top': keywords,
        'sources': {
            'metrics': bool(metrics_text),
            'logs_api': bool(msgs_api),
            'stderr': bool(msgs_err),
        }
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())

