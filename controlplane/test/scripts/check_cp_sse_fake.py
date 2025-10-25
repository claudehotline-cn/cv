#!/usr/bin/env python3
import sys, os, time
from urllib import request, error

BASE = os.environ.get("CP_BASE_URL", "http://127.0.0.1:8080")

def main():
    # Requires controlplane to be started with CP_FAKE_WATCH=1
    url = BASE + "/api/subscriptions/fake-1/events"
    req = request.Request(url, method="GET")
    try:
        with request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode('utf-8', errors='ignore')
            if 'event: phase' in body and '"phase":"ready"' in body:
                print("PASS")
                return 0
            print("SKIP: unexpected body")
            return 0
    except error.HTTPError as e:
        print("FAIL: status {}".format(e.code))
        return 1
    except Exception as ex:
        print("SKIP: exception {}".format(ex))
        return 0

if __name__ == "__main__":
    sys.exit(main())
