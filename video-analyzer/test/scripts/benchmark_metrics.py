#!/usr/bin/env python3
"""
Quick benchmark sampler for VA Prometheus metrics.

Reads /metrics, computes average FPS and per-stage P50/P95 latency from
histograms (va_frame_latency_ms) over a sampling window.

Usage:
  python3 benchmark_metrics.py --metrics http://127.0.0.1:9090/metrics --duration 30 --label tensorrt-native

Note: For multi-source scenarios, this aggregates by averaging across sources.
"""
from __future__ import annotations
import argparse
import time
import requests
from typing import Dict, Tuple, List
import json


def fetch_metrics(url: str, timeout: float = 3.0) -> str:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


def parse_fps(text: str) -> List[float]:
    fps = []
    for line in text.splitlines():
        if not line.startswith('va_pipeline_fps'):
            continue
        if line.startswith('#'):
            continue
        try:
            val = float(line.split()[-1])
            fps.append(val)
        except Exception:
            pass
    return fps


def parse_stage_hist(text: str) -> Dict[str, Dict[str, List[Tuple[float, float]]]]:
    """
    Returns: { stage: { source_id:path -> [(le, cumulative_count), ...], 'sum': float, 'count': float } }
    We will aggregate across sources later.
    """
    import re
    bucket_prefix = 'va_frame_latency_ms_bucket'
    sum_prefix = 'va_frame_latency_ms_sum'
    count_prefix = 'va_frame_latency_ms_count'
    rx_bucket = re.compile(r"^va_frame_latency_ms_bucket\{([^}]*)\} (\d+(?:\.\d+)?)$")
    rx_sum = re.compile(r"^va_frame_latency_ms_sum\{([^}]*)\} (\d+(?:\.\d+)?)$")
    rx_count = re.compile(r"^va_frame_latency_ms_count\{([^}]*)\} (\d+(?:\.\d+)?)$")

    stages: Dict[str, Dict[str, List[Tuple[float, float]]]] = {}
    sums: Dict[Tuple[str,str], float] = {}
    counts: Dict[Tuple[str,str], float] = {}

    def parse_labels(lbl: str) -> Dict[str,str]:
        out = {}
        for kv in lbl.split(','):
            kv = kv.strip()
            if not kv:
                continue
            k, v = kv.split('=')
            out[k] = v.strip('"')
        return out

    for line in text.splitlines():
        if line.startswith('#'):
            continue
        m = rx_bucket.match(line)
        if m:
            lbls = parse_labels(m.group(1))
            stage = lbls.get('stage','')
            source = lbls.get('source_id','')
            path = lbls.get('path','')
            le = lbls.get('le','')
            try:
                le_v = float('inf') if le == '+Inf' else float(le)
                val = float(m.group(2))
            except Exception:
                continue
            key = f"{source}:{path}" if source or path else 'default'
            stages.setdefault(stage, {}).setdefault(key, []).append((le_v, val))
            continue
        m = rx_sum.match(line)
        if m:
            lbls = parse_labels(m.group(1))
            key = (lbls.get('stage',''), f"{lbls.get('source_id','')}:{lbls.get('path','')}")
            try:
                sums[key] = float(m.group(2))
            except Exception:
                pass
            continue
        m = rx_count.match(line)
        if m:
            lbls = parse_labels(m.group(1))
            key = (lbls.get('stage',''), f"{lbls.get('source_id','')}:{lbls.get('path','')}")
            try:
                counts[key] = float(m.group(2))
            except Exception:
                pass
            continue

    # Attach sum/count
    for (stage, key), s in sums.items():
        stages.setdefault(stage, {}).setdefault(key, [])  # ensure key exists
        # we store special entries with le=inf for completeness; counts used below
    for (stage, key), c in counts.items():
        stages.setdefault(stage, {}).setdefault(key, [])
    return stages


def approx_quantile_from_buckets(buckets: List[Tuple[float, float]], q: float) -> float:
    """Approximate quantile from cumulative histogram buckets.
    Expects list sorted by increasing 'le'. Returns ms values (since our metric is ms buckets).
    """
    if not buckets:
        return 0.0
    buckets = sorted(buckets, key=lambda x: x[0])
    total = buckets[-1][1]
    if total <= 0:
        return 0.0
    target = total * q
    prev_c = 0.0
    prev_le = 0.0
    for le, c in buckets:
        if c >= target:
            # linear interpolate within this bucket (best-effort)
            width = max(le - prev_le, 1e-6)
            inc = c - prev_c
            if inc <= 0:
                return le
            frac = max(0.0, min(1.0, (target - prev_c) / inc))
            return prev_le + frac * width
        prev_c, prev_le = c, le
    return buckets[-1][0]


def aggregate_latency(stages: Dict[str, Dict[str, List[Tuple[float,float]]]]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for stage, series in stages.items():
        # Aggregate by averaging quantiles across keys
        p50s: List[float] = []
        p95s: List[float] = []
        for key, buckets in series.items():
            p50s.append(approx_quantile_from_buckets(buckets, 0.50))
            p95s.append(approx_quantile_from_buckets(buckets, 0.95))
        if p50s:
            out[stage] = {
                'p50': sum(p50s)/len(p50s),
                'p95': sum(p95s)/len(p95s)
            }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--metrics', default='http://127.0.0.1:9090/metrics')
    ap.add_argument('--duration', type=float, default=30.0)
    ap.add_argument('--label', default='run')
    args = ap.parse_args()

    t_end = time.time() + max(1.0, args.duration)
    fps_samples: List[float] = []
    last_text = ''
    while time.time() < t_end:
        try:
            text = fetch_metrics(args.metrics, timeout=3.0)
            fps_samples.extend(parse_fps(text))
            last_text = text
        except Exception:
            pass
        time.sleep(1.0)

    fps = sum(fps_samples)/len(fps_samples) if fps_samples else 0.0
    stages = parse_stage_hist(last_text) if last_text else {}
    lat = aggregate_latency(stages)
    result = {
        'label': args.label,
        'fps': round(fps, 3),
        'latency_ms': {k: {'p50': round(v.get('p50',0.0),3), 'p95': round(v.get('p95',0.0),3)} for k,v in lat.items()}
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

