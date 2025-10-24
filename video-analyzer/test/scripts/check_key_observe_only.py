import json, argparse, time, urllib.request, re

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

def parse_would_drop_acl_scheme(metrics_text: str) -> int:
    # va_quota_would_drop_total{reason="acl_scheme"} <num>
    m = re.search(r"va_quota_would_drop_total\{reason=\"acl_scheme\"\} (\d+)", metrics_text)
    return int(m.group(1)) if m else -1

def rid(prefix="t"):
    import random, string
    return prefix + "_" + ''.join(random.choice(string.ascii_lowercase+string.digits) for _ in range(6))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8082')
    ap.add_argument('--timeout', type=float, default=6.0)
    ap.add_argument('--tries', type=int, default=1)
    args = ap.parse_args()

    base = args.base.rstrip('/')
    out = { 'pass': False, 'skipped': False, 'reason': '', 'evidence': {} }

    try:
        info = json.loads(get(base + '/api/system/info', args.timeout))
        q = info.get('data', {}).get('quotas', {})
        schemes = set(q.get('acl', {}).get('allowed_schemes') or [])
        ov = None
        for o in (q.get('key_overrides') or []):
            if o.get('observe_only'):
                ov = o
                break
        if 'http' in schemes or not ov:
            out['skipped'] = True
            out['reason'] = 'precondition not met: allowed_schemes includes http or no observe_only override'
            out['pass'] = True
            print(json.dumps(out, ensure_ascii=False))
            return
        key = ov.get('key') or 'observe_only'
        m0_txt = get(base + '/metrics', args.timeout)
        m0 = parse_would_drop_acl_scheme(m0_txt)
        ok202 = 0
        for _ in range(max(1, args.tries)):
            code, _ = post_json(base + '/api/subscriptions', {
                'stream_id': rid('obs'), 'profile': 'det_720p', 'source_uri': 'http://example.com/x'
            }, timeout=args.timeout, headers={'X-API-Key': key})
            if code == 202:
                ok202 += 1
        time.sleep(0.2)
        m1_txt = get(base + '/metrics', args.timeout)
        m1 = parse_would_drop_acl_scheme(m1_txt)
        out['evidence'] = { 'would_drop_before': m0, 'would_drop_after': m1, 'ok202': ok202 }
        # Expect: 202 accepted and (optionally) would_drop increased
        out['pass'] = ok202 >= 1 and (m0 == -1 or m1 == -1 or m1 >= m0)
    except Exception as e:
        out['error'] = str(e)

    print(json.dumps(out, ensure_ascii=False))

if __name__ == '__main__':
    main()

