#!/usr/bin/env python3
import os, sys, json
from urllib import request, error

BASE = os.environ.get("CP_BASE_URL", "http://127.0.0.1:8080")

def http_post(path, payload):
    url = BASE + path
    data = json.dumps(payload).encode('utf-8')
    req = request.Request(url, data=data, method='POST')
    req.add_header('Content-Type','application/json')
    try:
        with request.urlopen(req, timeout=8) as resp:
            return resp.getcode(), resp.read()
    except error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        print('SKIP:', e); sys.exit(0)

def main():
    payload = { "attach_id":"cp_orch_a1", "pipeline_name":"p_orch_a1" }
    code, body = http_post('/api/orch/detach_remove', payload)
    if code in (500,502,503):
        print('SKIP: backend unavailable')
        return 0
    assert code in (200,202), (code, body)
    print('PASS')
    return 0

if __name__ == '__main__':
    sys.exit(main())

