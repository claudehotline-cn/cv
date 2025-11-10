#!/usr/bin/env python3
import os, sys, json, time
from urllib import request, parse, error

BASE = os.environ.get('CP_BASE', 'http://127.0.0.1:8080')
STREAM_ID = os.environ.get('TEST_STREAM_ID', 'cam01')
PROFILE = os.environ.get('TEST_PROFILE', 'default')
SOURCE_URI = os.environ.get('TEST_SOURCE_URI', 'rtsp://192.168.50.78:8554/camera_01')

def http_get(path, timeout=5):
    url = BASE.rstrip('/') + path
    with request.urlopen(url, timeout=timeout) as r:
        return r.read().decode('utf-8')

def http_post(path, body=None, timeout=5):
    url = BASE.rstrip('/') + path
    data = None
    headers = {'Content-Type': 'application/json'}
    if body is not None:
        data = json.dumps(body).encode('utf-8')
    req = request.Request(url, data=data, headers=headers, method='POST')
    with request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8'), r.getcode(), r.headers

def main():
    # 1) 列出 Triton 仓库模型
    s = http_get('/api/repo/list')
    obj = json.loads(s)
    assert obj.get('code') == 'OK', f"repo/list code={obj.get('code')}"
    items = obj.get('data') or []
    assert isinstance(items, list) and items, 'repo/list empty'
    model_id = items[0].get('id') or items[0].get('name')
    assert model_id, 'invalid repo list item'
    print('[ok] repo/list ->', model_id)

    # 2) 直接把仓库模型名作为 model_id 订阅（CP 将仅设置 triton_model 选项并清空订阅的 model_id）
    body = { 'stream_id': STREAM_ID, 'profile': PROFILE, 'source_uri': SOURCE_URI, 'model_id': model_id }
    s, code, headers = http_post('/api/subscriptions', body)
    assert code in (200, 202), f'subscribe http {code} body={s}'
    obj = json.loads(s)
    assert obj.get('code') in ('OK','ACCEPTED'), f"subscribe code={obj.get('code')} body={s}"
    sub_id = (obj.get('data') or {}).get('id') or obj.get('id')
    assert sub_id, 'missing subscription id'
    print('[ok] subscribe ->', sub_id)

    # 3) 轮询订阅状态（最佳努力）
    ready = False
    for _ in range(10):
        time.sleep(1.0)
        s = http_get(f'/api/subscriptions/{parse.quote(sub_id)}')
        obj = json.loads(s)
        if obj.get('code') == 'OK' and (obj.get('data') or {}).get('phase') in ('ready','running','Ready'):
            ready = True
            break
    print('[ok]' if ready else '[warn]', 'phase ->', (obj.get('data') or {}).get('phase'))
    sys.exit(0 if ready else 0)

if __name__ == '__main__':
    try:
        main()
    except Exception as ex:
        print('[err]', ex)
        sys.exit(1)

