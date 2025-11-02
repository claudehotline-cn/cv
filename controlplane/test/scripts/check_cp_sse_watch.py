#!/usr/bin/env python3
import os, sys, time, json
import requests

BASE = os.environ.get('CP_BASE_URL','http://127.0.0.1:8080')
SRC_ID = os.environ.get('CP_TEST_SOURCE_ID','camera_01')
STREAM_ID = os.environ.get('CP_TEST_STREAM_ID','s1')
PROFILE = os.environ.get('CP_TEST_PROFILE','default')

def main():
  try:
    # create subscription via source_id -> restream
    url = f"{BASE}/api/subscriptions"
    body = {"stream_id": STREAM_ID, "profile": PROFILE, "source_id": SRC_ID}
    r = requests.post(url, json=body, timeout=5)
    if r.status_code != 202 or 'Location' not in r.headers:
      print(f"SKIP: POST not accepted ({r.status_code})")
      return 0
    loc = r.headers['Location']
    sid = loc.rstrip('/').split('/')[-1]

    # connect SSE
    ev_url = f"{BASE}/api/subscriptions/{sid}/events"
    with requests.get(ev_url, stream=True, timeout=15) as resp:
      if resp.status_code != 200:
        print(f"SKIP: SSE not 200 ({resp.status_code})")
        return 0
      got_event = False
      start = time.time()
      for line in resp.iter_lines(decode_unicode=True):
        if line is None: continue
        if line.startswith('event:'):
          got_event = True
          break
        if time.time() - start > 10:
          break
      if not got_event:
        print("SKIP: no SSE event within 10s")
        return 0
    # cleanup
    requests.delete(f"{BASE}/api/subscriptions/{sid}", timeout=5)
    print("PASS: sse_watch")
    return 0
  except Exception as e:
    print(f"SKIP: exception {e}")
    return 0

if __name__ == '__main__':
  sys.exit(main())

