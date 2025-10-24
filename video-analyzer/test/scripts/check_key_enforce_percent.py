import json, argparse, time, urllib.request

def get(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode('utf-8')

def post_json(url, data, timeout=5.0, headers=None):
    body = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={'Content-Type':'application/json', **(headers or {})}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.getcode(), r.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='ignore')

def rid(prefix="t"):
    import random, string
    return prefix + "_" + ''.join(random.choice(string.ascii_lowercase+string.digits) for _ in range(6))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8082')
    ap.add_argument('--timeout', type=float, default=6.0)
    ap.add_argument('--tries', type=int, default=16)
    ap.add_argument('--uri', default='rtsp://127.0.0.1:8554/camera_01')
    args = ap.parse_args()

    base = args.base.rstrip('/')
    out = { 'pass': False, 'skipped': False, 'reason': '', 'stats': {} }
    try:
        info = json.loads(get(base + '/api/system/info', args.timeout))
        q = info.get('data', {}).get('quotas', {})
        schemes = set(q.get('acl', {}).get('allowed_schemes') or [])
        ov = None
        for o in (q.get('key_overrides') or []):
            ep = o.get('enforce_percent', -1)
            if isinstance(ep, int) and 0 < ep < 100:
                ov = o
                break
        if 'http' in schemes or not ov:
            out['skipped'] = True
            out['reason'] = 'precondition not met: allowed_schemes includes http or no enforce_percent(1..99) override'
            out['pass'] = True
            print(json.dumps(out, ensure_ascii=False))
            return
        key = ov.get('key') or 'canary'
        ok202 = 0; r429 = 0
        for _ in range(max(3, args.tries)):
            code, _ = post_json(base + '/api/subscriptions', {
                'stream_id': rid('can'), 'profile': 'det_720p', 'source_uri': args.uri
            }, timeout=args.timeout, headers={'X-API-Key': key})
            if code == 202: ok202 += 1
            elif code == 429: r429 += 1
        out['stats'] = { 'ok202': ok202, 'r429': r429, 'tries': args.tries }
        out['pass'] = (ok202 >= 1 and r429 >= 1)
    except Exception as e:
        out['error'] = str(e)

    print(json.dumps(out, ensure_ascii=False))

if __name__ == '__main__':
    main()
