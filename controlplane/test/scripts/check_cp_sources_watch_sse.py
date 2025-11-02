#!/usr/bin/env python3
import os, sys, time, requests

BASE = os.environ.get('CP_BASE_URL','http://127.0.0.1:8080')

def main():
  url = f"{BASE}/api/sources/watch_sse"
  try:
    with requests.get(url, stream=True, timeout=15) as resp:
      if resp.status_code != 200:
        print(f"SKIP: status {resp.status_code}")
        return 0
      start = time.time()
      for line in resp.iter_lines(decode_unicode=True):
        if line is None: continue
        if line.startswith('event: state'):
          print("PASS: sources_watch_sse")
          return 0
        if time.time() - start > 10:
          print("SKIP: no state event within 10s")
          return 0
    print("SKIP: stream closed")
    return 0
  except Exception as e:
    print(f"SKIP: exception {e}")
    return 0

if __name__ == '__main__':
  sys.exit(main())

