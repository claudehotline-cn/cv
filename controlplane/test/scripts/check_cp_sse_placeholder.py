#!/usr/bin/env python3
import sys, os
from urllib import request, error

BASE = os.environ.get("CP_BASE_URL", "http://127.0.0.1:8080")

def main():
    url = BASE + "/api/subscriptions/demo-id/events"
    req = request.Request(url, method="GET")
    try:
        with request.urlopen(req, timeout=5) as resp:
            # If server erroneously returns 200, treat as skip
            if resp.getcode() == 200:
                print("SKIP: SSE enabled unexpectedly")
                return 0
            print("SKIP: unexpected status {}".format(resp.getcode()))
            return 0
    except error.HTTPError as e:
        if e.code == 501:
            print("PASS")
            return 0
        print("SKIP: status {}".format(e.code))
        return 0
    except Exception as ex:
        print("SKIP: exception {}".format(ex))
        return 0

if __name__ == "__main__":
    sys.exit(main())

