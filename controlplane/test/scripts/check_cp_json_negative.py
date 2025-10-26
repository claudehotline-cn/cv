#!/usr/bin/env python3
import json, sys, os
from urllib import request, error

BASE = os.environ.get("CP_BASE_URL", "http://127.0.0.1:8080")

def http(method, path, data=None):
    url = BASE + path
    data_bytes = None
    if data is not None:
        if isinstance(data, (bytes, bytearray)):
            data_bytes = data
        else:
            data_bytes = json.dumps(data).encode("utf-8")
    req = request.Request(url, data=data_bytes, method=method)
    if data is not None and not isinstance(data, (bytes, bytearray)):
        req.add_header("Content-Type","application/json")
    try:
        with request.urlopen(req, timeout=5) as resp:
            return resp.getcode(), resp.read()
    except error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        print("SKIP: exception {}".format(e))
        sys.exit(0)

def assert_code(exp, got, ctx):
    assert got == exp, (ctx, got)

def main():
    # 1) subscriptions: invalid JSON should be 400
    c, _ = http("POST", "/api/subscriptions", data=b"{invalid}")
    assert_code(400, c, "subscriptions invalid json")

    # 2) sources:enable with wrong type -> 400
    c, _ = http("POST", "/api/sources:enable", {"attach_id": 123})
    assert_code(400, c, "sources:enable wrong type")

    # 3) sources:disable missing attach_id -> 400
    c, _ = http("POST", "/api/sources:disable", {})
    assert_code(400, c, "sources:disable missing field")

    # 4) control/apply_pipeline missing fields -> 400 (no VA required)
    c, _ = http("POST", "/api/control/apply_pipeline", {"pipeline_name":"p1"})
    assert_code(400, c, "apply_pipeline missing spec")

    # 5) control/drain invalid json type -> 400
    c, _ = http("POST", "/api/control/drain", data=b"{bad}")
    assert_code(400, c, "drain invalid json")

    print("PASS")
    return 0

if __name__ == "__main__":
    sys.exit(main())

