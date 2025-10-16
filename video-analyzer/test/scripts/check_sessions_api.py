#!/usr/bin/env python3
import sys, json, urllib.request, urllib.parse

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8082'

def get(path, params=None):
    url = BASE + path
    if params:
        qs = urllib.parse.urlencode(params)
        url += ('?' + qs)
    with urllib.request.urlopen(url, timeout=3) as resp:
        if resp.status != 200:
            raise RuntimeError(f'HTTP {resp.status}')
        return json.loads(resp.read().decode('utf-8'))

def main():
    # health
    ping = get('/api/db/ping')
    assert ping.get('ok') is True, 'db ping not ok'

    # basic list
    j = get('/api/sessions', {'limit': 5})
    data = j.get('data', {})
    items = data.get('items', [])
    assert isinstance(items, list), 'items not list'

    # paginated within time-window (last 30 days)
    import time
    now_ms = int(time.time()*1000)
    from_ms = now_ms - 30*24*3600*1000
    j2 = get('/api/sessions', {'page': 1, 'page_size': 20, 'from_ts': from_ms, 'to_ts': now_ms})
    d2 = j2.get('data', {})
    total = int(d2.get('total', 0))
    assert total >= 0, 'total missing'

    print(json.dumps({
        'ok': True,
        'basic_count': len(items),
        'total': total,
        'sample': items[0] if items else None
    }, ensure_ascii=False))

if __name__ == '__main__':
    main()

