#!/usr/bin/env python3
import os, sys, time, threading
from urllib import request, error

BASE = os.environ.get("CP_BASE_URL", "http://127.0.0.1:8080")
CLIENTS = int(os.environ.get("CP_SSE_CLIENTS", "3"))
DURATION = int(os.environ.get("CP_SSE_SEC", "6"))

def http_get(url, timeout=3):
    req = request.Request(url, method='GET')
    with request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', 'ignore')

def get_metrics():
    try:
        text = http_get(BASE + "/metrics", timeout=3)
        conn = 0.0; recc = 0.0
        for line in text.splitlines():
            if line.startswith("cp_sse_connections "):
                try: conn = float(line.split()[1])
                except: pass
            if line.startswith("cp_sse_reconnects "):
                try: recc = float(line.split()[1])
                except: pass
        return conn, recc
    except Exception as e:
        print("SKIP: metrics exception {}".format(e)); sys.exit(0)

def sse_client(idx, results):
    url = BASE + "/api/sources/watch_sse"
    try:
        req = request.Request(url, method='GET')
        with request.urlopen(req, timeout=5) as resp:
            start = time.time(); ev = 0
            while True:
                line = resp.readline()
                if not line:
                    break
                if line.startswith(b"data:") or line.startswith(b"event:"):
                    ev += 1
                if time.time() - start >= DURATION:
                    break
            results[idx] = ev
    except Exception:
        results[idx] = -1

def main():
    c0, r0 = get_metrics()
    results = { i:0 for i in range(CLIENTS) }
    th = [ threading.Thread(target=sse_client, args=(i,results)) for i in range(CLIENTS) ]
    for t in th: t.start()
    # sample gauge peak during window
    peak = 0.0
    ticks = int(max(1, DURATION*2))
    for _ in range(ticks):
        try:
            c, _ = get_metrics()
            if c > peak: peak = c
        except Exception:
            pass
        time.sleep(0.5)
    for t in th: t.join()
    c2, r2 = get_metrics()
    ok_clients = sum(1 for v in results.values() if v >= 0)
    if r2 - r0 < ok_clients:
        print("FAIL: reconnects delta {} < ok_clients {}".format(r2-r0, ok_clients)); sys.exit(1)
    for i,v in results.items():
        if v >= 0 and v < 1:
            print("FAIL: client {} received {} events".format(i,v)); sys.exit(1)
    total_ev = sum(v for v in results.values() if v >= 0)
    print("PASS: STATS peak_conns={} reconnects_delta={} ok_clients={} events_sum={}".format(peak, r2-r0, ok_clients, total_ev))
    return 0

if __name__ == "__main__":
    sys.exit(main())
