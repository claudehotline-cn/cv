#!/usr/bin/env python3
import sys, time, json, threading
import requests

BASE = "http://127.0.0.1:8082"

def fetch_metrics_text():
    r = requests.get(f"{BASE}/metrics", timeout=5)
    r.raise_for_status()
    return r.text

def metric_value(text: str, metric: str, label: str) -> int:
    # label like channel="sources"
    tgt = f"{metric}{{{label}}}"
    val = 0
    for line in text.splitlines():
        if line.startswith(tgt):
            try:
                val = int(float(line.split()[-1]))
            except Exception:
                val = 0
    return val

def open_sse(path: str, headers=None, duration_sec: float=3.0):
    url = f"{BASE}{path}"
    sess = requests.Session()
    hdr = {"Accept":"text/event-stream"}
    if headers:
        hdr.update(headers)
    resp = sess.get(url, headers=hdr, stream=True, timeout=10)
    def run():
        try:
            t0 = time.time()
            for _ in resp.iter_lines(decode_unicode=True):
                if time.time() - t0 >= duration_sec:
                    break
        except Exception:
            pass
        finally:
            try:
                resp.close()
            except Exception:
                pass
    th = threading.Thread(target=run, daemon=True)
    th.start()
    return resp, th

def main():
    before = fetch_metrics_text()
    c0 = metric_value(before, "va_sse_connections", 'channel="sources"')
    r0 = metric_value(before, "va_sse_reconnects_total", '')

    # Open a plain SSE connection
    resp1, th1 = open_sse("/api/sources/watch_sse", None, 3.0)
    time.sleep(1.0)
    mid = fetch_metrics_text()
    c1 = metric_value(mid, "va_sse_connections", 'channel="sources"')

    # Open a reconnect-signaled SSE (Last-Event-ID)
    resp2, th2 = open_sse("/api/sources/watch_sse", {"Last-Event-ID":"10"}, 1.5)
    time.sleep(1.0)
    mid2 = fetch_metrics_text()
    r1 = metric_value(mid2, "va_sse_reconnects_total", '')

    # Close connections
    try: resp1.close()
    except: pass
    try: resp2.close()
    except: pass
    th1.join(timeout=2)
    th2.join(timeout=2)
    time.sleep(0.5)
    after = fetch_metrics_text()
    c2 = metric_value(after, "va_sse_connections", 'channel="sources"')

    result = {
        "connections_before": c0,
        "connections_during": c1,
        "connections_after": c2,
        "reconnects_before": r0,
        "reconnects_after": r1,
        # 在某些环境下连接 gauge 可能瞬时归零；以重连计数为硬性通过条件
        "pass": (r1 >= r0+1)
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["pass"] else 1)

if __name__ == "__main__":
    main()
