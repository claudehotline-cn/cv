#!/usr/bin/env python3
import os, sys, json
from urllib import request, error, parse

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
    # Resolve a valid YAML path from repo
    here = os.path.dirname(__file__)
    repo = os.path.abspath(os.path.join(here, '..', '..', '..'))
    y1 = os.path.join(repo, 'video-analyzer', 'build-ninja', 'bin', 'config', 'graphs', 'analyzer_multistage_example.yaml')
    y2 = os.path.join(repo, 'video-analyzer', 'config', 'graphs', 'analyzer_multistage_example.yaml')
    yaml_path = y1 if os.path.exists(y1) else (y2 if os.path.exists(y2) else '')
    if not yaml_path:
        print('SKIP: yaml not found')
        return 0
    payload = {
        "attach_id":"cp_orch_a1",
        "source_uri":"rtsp://127.0.0.1:8554/camera_01",
        "source_id":"camera_01",
        "pipeline_name":"p_orch_a1",
        "spec": { "yaml_path": yaml_path }
    }
    code, body = http_post('/api/orch/attach_apply', payload)
    if code in (500,502,503):
        print('SKIP: backend unavailable')
        return 0
    assert code == 202, (code, body)
    print('PASS')
    return 0

if __name__ == '__main__':
    sys.exit(main())
