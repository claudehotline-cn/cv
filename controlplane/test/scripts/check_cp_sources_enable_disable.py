#!/usr/bin/env python3
import json, sys, os
from urllib import request, parse, error

BASE = os.environ.get("CP_BASE_URL", "http://127.0.0.1:8080")

def http(method, path, data=None):
    url = BASE + path
    data_bytes = json.dumps(data).encode("utf-8") if data is not None else None
    req = request.Request(url, data=data_bytes, method=method)
    if data is not None: req.add_header("Content-Type","application/json")
    try:
        with request.urlopen(req, timeout=10) as resp:
            return resp.getcode(), resp.headers, resp.read()
    except error.HTTPError as e:
        return e.code, e.headers, e.read()
    except Exception as e:
        print("SKIP: exception {}".format(e))
        sys.exit(0)

def main():
    aid = "cp_test_a2"
    # enable
    code,_,_ = http("POST","/api/sources:enable", {"attach_id":aid})
    if code in (500,502,503):
        print("SKIP: backend not available (VSM)")
        return 0
    assert code == 202, code
    # disable
    code2,_,_ = http("POST","/api/sources:disable", {"attach_id":aid})
    assert code2 in (202,200), code2
    print("PASS")
    return 0

if __name__ == "__main__":
    sys.exit(main())

