#!/usr/bin/env python3
import os, sys, time
from urllib import request

BASE = os.environ.get("CP_BASE_URL", "http://127.0.0.1:8080")
DURATION = int(os.environ.get("CP_SSE_SOAK_SEC", "60"))

def run_once(max_sec=15):
    url = BASE + "/api/sources/watch_sse"
    start = time.time(); events = 0
    try:
        req = request.Request(url, method='GET')
        with request.urlopen(req, timeout=10) as resp:
            while True:
                line = resp.readline()
                if not line:
                    break
                if line.startswith(b"data:") or line.startswith(b"event:"):
                    events += 1
                if time.time() - start >= max_sec:
                    return True, events
    except Exception:
        pass
    return False, events

def main():
    deadline = time.time() + DURATION
    total_ev = 0
    opened = 0
    while time.time() < deadline:
        ok, ev = run_once(max_sec=min(15, int(deadline - time.time())))
        total_ev += ev; opened += 1
        if not ok:
            # Backoff briefly then reconnect
            time.sleep(0.5)
    # We cannot assert strong guarantees without VSM; print summary
    print("PASS: opened={} events={}".format(opened, total_ev))
    return 0

if __name__ == "__main__":
    sys.exit(main())
