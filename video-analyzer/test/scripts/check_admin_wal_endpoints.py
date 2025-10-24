import json
import sys
import time
from urllib import request, parse

BASE = "http://127.0.0.1:8082"

def http_get(path, timeout=5):
    with request.urlopen(BASE + path, timeout=timeout) as resp:
        body = resp.read().decode('utf-8')
        return json.loads(body)

def main():
    # Wait briefly for server to be healthy
    for _ in range(10):
        try:
            ok = http_get('/api/system/info')
            if ok.get('code') == 'OK':
                break
        except Exception:
            time.sleep(0.2)
    s = http_get('/api/admin/wal/summary')
    assert s.get('code') == 'OK', f"unexpected code: {s}"
    data = s.get('data', {})
    assert isinstance(data.get('enabled'), bool), "enabled must be bool"
    assert isinstance(data.get('failed_restart'), int), "failed_restart must be int"
    t = http_get('/api/admin/wal/tail?n=3')
    assert t.get('code') == 'OK', f"unexpected code: {t}"
    data2 = t.get('data', {})
    assert isinstance(data2.get('count'), int), "count must be int"
    items = data2.get('items')
    assert isinstance(items, list), "items must be list"
    print('admin wal endpoints: OK')

if __name__ == '__main__':
    main()

