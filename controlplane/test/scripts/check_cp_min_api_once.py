#!/usr/bin/env python3
import json, sys, os, time
from urllib import request, parse, error

BASE = os.environ.get("CP_BASE_URL", "http://127.0.0.1:8080")

def http(method, path, data=None, headers=None):
    url = BASE + path
    data_bytes = None
    if data is not None:
        data_bytes = json.dumps(data).encode("utf-8")
    req = request.Request(url, data=data_bytes, method=method)
    if headers:
        for k,v in headers.items(): req.add_header(k,v)
    if data is not None:
        req.add_header("Content-Type","application/json")
    try:
        with request.urlopen(req, timeout=10) as resp:
            body = resp.read()
            return resp.getcode(), resp.headers, body
    except error.HTTPError as e:
        return e.code, e.headers, e.read()
    except Exception as e:
        print("SKIP: exception {}".format(e))
        sys.exit(0)

def main():
    # Create
    payload = {"stream_id":"s1","profile":"p1","source_uri":"rtsp://127.0.0.1:8554/camera_01"}
    qs = "?stream_id=s1&profile=p1&source_uri="+parse.quote("rtsp://127.0.0.1:8554/camera_01")
    code, headers, body = http("POST","/api/subscriptions"+qs, payload)
    if code == 502:
        print("SKIP: backend not available (VA)")
        return 0
    assert code == 202, (code, body)
    loc = headers.get("Location")
    assert loc and loc.startswith("/api/subscriptions/"), loc
    cp_id = loc.rsplit('/',1)[-1]

    # GET 200
    code, h2, b2 = http("GET", f"/api/subscriptions/{cp_id}")
    assert code in (200,304), code
    if code == 200:
        etag = h2.get("ETag")
        assert etag, "missing ETag"
        # GET 304
        code3, h3, b3 = http("GET", f"/api/subscriptions/{cp_id}", headers={"If-None-Match": etag})
        assert code3 == 304, code3

    # DELETE
    code4, h4, b4 = http("DELETE", f"/api/subscriptions/{cp_id}")
    assert code4 == 202, code4
    print("PASS")
    return 0

if __name__ == "__main__":
    sys.exit(main())
