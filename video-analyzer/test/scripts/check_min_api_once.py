#!/usr/bin/env python3
import sys
import json
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8082"

def http_req(req, timeout=10):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            headers = dict(resp.getheaders())
            body = resp.read().decode("utf-8", errors="ignore")
            return code, headers, body
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read().decode("utf-8", errors="ignore")

def post_subscription(stream_id, profile, uri, key=None, use_existing=False, timeout=15):
    data = json.dumps({"stream_id": stream_id, "profile": profile, "source_uri": uri}).encode("utf-8")
    url = f"{BASE}/api/subscriptions"
    if use_existing:
        url += "?use_existing=1"
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    if key:
        req.add_header("X-API-Key", key)
    return http_req(req, timeout=timeout)

def get_subscription(sub_id, timeout=10):
    url = f"{BASE}/api/subscriptions/{sub_id}"
    req = urllib.request.Request(url)
    return http_req(req, timeout=timeout)

def delete_subscription(sub_id, timeout=10):
    url = f"{BASE}/api/subscriptions/{sub_id}"
    req = urllib.request.Request(url, method="DELETE")
    return http_req(req, timeout=timeout)

def main():
    stream_id = "smoke_cam"
    profile = "det_720p"
    uri = "rtsp://127.0.0.1:8554/camera_01"
    key = "vip-observe"

    code, headers, _ = post_subscription(stream_id, profile, uri, key=key, use_existing=True)
    if code != 202 or "Location" not in headers:
        print(json.dumps({"pass": False, "phase": None, "error": f"POST status={code}"}, ensure_ascii=False))
        return 1
    sub_id = headers["Location"].split("/")[-1]

    phase = None
    ok_get = False
    for i in range(5):
        code2, _, body2 = get_subscription(sub_id, timeout=15)
        if code2 == 200:
            try:
                data = json.loads(body2)
                phase = data.get("data", {}).get("phase")
                ok_get = True
                break
            except Exception:
                pass
        time.sleep(0.5 + 0.2 * i)

    ok_del = False
    for i in range(4):
        code3, _, _ = delete_subscription(sub_id, timeout=12)
        if code3 == 202:
            ok_del = True
            break
        time.sleep(0.5 + 0.2 * i)

    passed = (ok_get and ok_del)
    print(json.dumps({"pass": passed, "id": sub_id, "phase": phase, "get": ok_get, "delete": ok_del}, ensure_ascii=False))
    return 0 if passed else 1

if __name__ == "__main__":
    sys.exit(main())

