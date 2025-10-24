import json, argparse, random, string, urllib.request

def rid(prefix="t"):
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
    out = { 'pass': False, 'checks': {}, 'skips': [] }

    info = get_json(base + '/api/system/info', timeout=args.timeout)
    quotas = info.get('data', {}).get('quotas', {})
    allowed_schemes = set(quotas.get('acl', {}).get('allowed_schemes', []) or [])
    allowed_profiles = set(quotas.get('acl', {}).get('allowed_profiles', []) or [])

    # 1) Allowed scheme/profile should accept 202
    stream_id = rid('ok')
    profile = next(iter(allowed_profiles), 'det_720p') or 'det_720p'
    uri = 'rtsp://127.0.0.1:8554/camera_01'
    code, _ = post_json(base + '/api/subscriptions', { 'stream_id': stream_id, 'profile': profile, 'source_uri': uri }, timeout=args.timeout, headers={'X-API-Key': rid('k')})
    out['checks']['allowed_202'] = (code == 202)

    # 2) Disallowed scheme -> 403 (if applicable)
    if 'http' not in allowed_schemes:
        stream_id = rid('sch')
        code2, body2 = post_json(base + '/api/subscriptions', { 'stream_id': stream_id, 'profile': profile, 'source_uri': 'http://example.com/x' }, timeout=args.timeout, headers={'X-API-Key': rid('k')})
        out['checks']['disallowed_scheme_403'] = (code2 == 403)
    else:
        out['skips'].append('allowed_schemes includes http')

    # 3) Disallowed profile -> 403 (if allowed_profiles list exists)
    if allowed_profiles:
        bad_profile = 'invalid_profile_' + rid('p')
        stream_id = rid('prf')
        code3, _ = post_json(base + '/api/subscriptions', { 'stream_id': stream_id, 'profile': bad_profile, 'source_uri': uri }, timeout=args.timeout, headers={'X-API-Key': rid('k')})
        out['checks']['disallowed_profile_403'] = (code3 == 403)
    else:
        out['skips'].append('allowed_profiles not configured')

    out['pass'] = all(out['checks'].values())
    print(json.dumps(out, ensure_ascii=False))

if __name__ == '__main__':
    main()

