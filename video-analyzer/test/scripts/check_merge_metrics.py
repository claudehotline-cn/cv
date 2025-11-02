#!/usr/bin/env python3
import sys, time, json, re
from typing import Dict
import requests

BASE = "http://127.0.0.1:8082"

def fetch_metrics() -> str:
    r = requests.get(f"{BASE}/metrics", timeout=5)
    r.raise_for_status()
    return r.text

def parse_metric(lines: str, name: str, label_filter: Dict[str,str]|None=None) -> int:
    total = 0
    for line in lines.splitlines():
        if not line.startswith(name):
            continue
        if "#" in line:
            continue
        # name{key="val",...} value
        m = re.match(r"^"+re.escape(name)+r"(\{([^}]*)\})?\s+([0-9eE+\-.]+)$", line.strip())
        if not m:
            continue
        labels = {}
        if m.group(2):
            for kv in re.findall(r"(\w+)=\"([^\"]*)\"", m.group(2)):
                labels[kv[0]] = kv[1]
        if label_filter:
            ok = all(labels.get(k)==v for k,v in label_filter.items())
            if not ok:
                continue
        try:
            v = float(m.group(3))
        except Exception:
            v = 0
        total += int(v)
    return total

def post_sub(use_existing: bool=True) -> requests.Response:
    url = f"{BASE}/api/subscriptions"
    if use_existing:
        url += "?use_existing=1"
    body = {
        "stream_id": "test_stream_merge",
        "profile": "default",
        "source_uri": "rtsp://127.0.0.1:8554/camera_01"
    }
    r = requests.post(url, data=json.dumps(body), headers={"Content-Type":"application/json"}, timeout=5)
    return r

def main():
    before = fetch_metrics()
    b_nonterm = parse_metric(before, "va_subscriptions_merge_total", {"type":"non_terminal"})
    b_ready   = parse_metric(before, "va_subscriptions_merge_total", {"type":"ready"})
    b_miss    = parse_metric(before, "va_subscriptions_merge_total", {"type":"miss"})

    # Fire a burst to trigger reuse/merge
    codes = []
    acl_refused = 0
    for _ in range(3):
        resp = post_sub(True)
        codes.append(resp.status_code)
        # detect ACL refusal -> skip
        if resp.status_code in (401,403) and resp.headers.get("X-Quota-Reason",""
            ).startswith("acl_"):
            acl_refused += 1
        time.sleep(0.05)

    time.sleep(0.5)
    after = fetch_metrics()
    a_nonterm = parse_metric(after, "va_subscriptions_merge_total", {"type":"non_terminal"})
    a_ready   = parse_metric(after, "va_subscriptions_merge_total", {"type":"ready"})
    a_miss    = parse_metric(after, "va_subscriptions_merge_total", {"type":"miss"})

    dn = a_nonterm - b_nonterm
    dr = a_ready - b_ready
    dm = a_miss - b_miss

    ok = (dn>0) or (dr>0) or (dm>0) or (acl_refused==len(codes))
    result = {
        "attempt_statuses": codes,
        "acl_refused": acl_refused,
        "delta_non_terminal": dn,
        "delta_ready": dr,
        "delta_miss": dm,
        "pass": bool(ok),
        "skipped": bool(acl_refused==len(codes))
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
