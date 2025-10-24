import json, argparse, random, string, urllib.request

def rid(prefix="t"):
    import random, string
    return prefix + "_" + ''.join(random.choice(string.ascii_lowercase+string.digits) for _ in range(6))

def post_json(url, data, timeout=5.0, headers=None):
    body = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={'Content-Type':'application/json', **(headers or {})}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.getcode(), r.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='ignore')

def get_json(url, timeout=5.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8082')
    ap.add_argument('--timeout', type=float, default=6.0)
    args = ap.parse_args()

    base = args.base.rstrip('/')
    out = { 'pass': False, 'skipped': False, 'reason': '' }

    info = get_json(base + '/api/system/info', timeout=args.timeout)
    q = info.get('data', {}).get('quotas', {})
    allowed_schemes = set(q.get('acl', {}).get('allowed_schemes', []) or [])
    exempt_keys = list(q.get('exempt_keys') or [])

    # Preconditions: need a disallowed scheme, and at least one exempt key
    if 'http' in allowed_schemes or not exempt_keys:
        out['skipped'] = True
        out['reason'] = 'precondition not met: http allowed or exempt_keys empty'
        out['pass'] = True
        print(json.dumps(out, ensure_ascii=False))
        return

    uri_disallowed = 'http://example.com/x'
    profile = 'det_720p'

    # Non-exempt request → 403
    code_bad, _ = post_json(base + '/api/subscriptions', {
        'stream_id': rid('nx'), 'profile': profile, 'source_uri': uri_disallowed
    }, timeout=args.timeout, headers={'X-API-Key': rid('k')})

    # Exempt request → 202 (bypass ACL/quotas)
    ex_key = exempt_keys[0]
    code_ok, _ = post_json(base + '/api/subscriptions', {
        'stream_id': rid('ex'), 'profile': profile, 'source_uri': uri_disallowed
    }, timeout=args.timeout, headers={'X-API-Key': ex_key})

    out['pass'] = (code_bad == 403 and code_ok == 202)
    print(json.dumps(out, ensure_ascii=False))

if __name__ == '__main__':
    main()

