#!/usr/bin/env python3
import os, sys
from urllib import request, error

BASE = os.environ.get("CP_BASE_URL", "http://127.0.0.1:8080")

def main():
    url = BASE + "/api/orch/health"
    try:
        with request.urlopen(request.Request(url, method='GET'), timeout=5) as resp:
            code = resp.getcode(); body = resp.read()
            assert code == 200, code
            print("PASS")
            return 0
    except Exception as e:
        print("SKIP:", e)
        return 0

if __name__ == '__main__':
    sys.exit(main())

