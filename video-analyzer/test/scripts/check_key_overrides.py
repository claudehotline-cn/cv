import json, argparse, time, urllib.request, random, string

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
    out = { 'pass': False, 'skipped': False, 'reason': '', 'checks': {} }

    info = get_json(base + '/api/system/info', timeout=args.timeout)
    q = info.get('data', {}).get('quotas', {})
    key_overrides = list(q.get('key_overrides') or [])
    default_cc = int(q.get('default', {}).get('concurrent', 1) or 1)
    default_rpm = int(q.get('default', {}).get('rate_per_min', 1) or 1)

    if not key_overrides:
        out['skipped'] = True
        out['reason'] = 'no key_overrides configured'
        out['pass'] = True
        print(json.dumps(out, ensure_ascii=False))
        return

    ov = key_overrides[0]
    ov_key = ov.get('key', '')
    ov_cc = int(ov.get('concurrent') or 0)
    ov_rpm = int(ov.get('rate_per_min') or 0)
    if not ov_key or (ov_cc <= default_cc and ov_rpm <= default_rpm):
        out['skipped'] = True
        out['reason'] = 'override not stronger than default'
        out['pass'] = True
        print(json.dumps(out, ensure_ascii=False))
        return

    # Use a valid scheme/profile to isolate quota behavior
    profile = 'det_720p'
    uri = 'rtsp://127.0.0.1:8554/camera_01'

    # A) Concurrent: send two quick requests for override key and control key
    if ov_cc > default_cc and ov_cc >= 2:
        # control: other key should fail the 2nd with 429
        ctrl_key = rid('ctrl')
        code1,_ = post_json(base + '/api/subscriptions', {'stream_id': rid('c1'),'profile':profile,'source_uri':uri}, headers={'X-API-Key': ctrl_key}, timeout=args.timeout)
        code2,_ = post_json(base + '/api/subscriptions', {'stream_id': rid('c2'),'profile':profile,'source_uri':uri}, headers={'X-API-Key': ctrl_key}, timeout=args.timeout)
        out['checks']['control_cc_429'] = (code1 in (202,429) and code2 == 429)
        # override: two should pass 202 (enforced path allows >=2)
        ok1,_ = post_json(base + '/api/subscriptions', {'stream_id': rid('o1'),'profile':profile,'source_uri':uri}, headers={'X-API-Key': ov_key}, timeout=args.timeout)
        ok2,_ = post_json(base + '/api/subscriptions', {'stream_id': rid('o2'),'profile':profile,'source_uri':uri}, headers={'X-API-Key': ov_key}, timeout=args.timeout)
        out['checks']['override_cc_202x2'] = (ok1 == 202 and ok2 == 202)

    # B) Rate-per-min: send two quick requests; control should 429, override should allow >=2
    if ov_rpm > default_rpm and ov_rpm >= 2:
        ctrl_key2 = rid('ctrl2')
        code3,_ = post_json(base + '/api/subscriptions', {'stream_id': rid('r1'),'profile':profile,'source_uri':uri}, headers={'X-API-Key': ctrl_key2}, timeout=args.timeout)
        code4,_ = post_json(base + '/api/subscriptions', {'stream_id': rid('r2'),'profile':profile,'source_uri':uri}, headers={'X-API-Key': ctrl_key2}, timeout=args.timeout)
        out['checks']['control_rpm_429'] = (code3 in (202,429) and code4 == 429)
        ok3,_ = post_json(base + '/api/subscriptions', {'stream_id': rid('or1'),'profile':profile,'source_uri':uri}, headers={'X-API-Key': ov_key}, timeout=args.timeout)
        ok4,_ = post_json(base + '/api/subscriptions', {'stream_id': rid('or2'),'profile':profile,'source_uri':uri}, headers={'X-API-Key': ov_key}, timeout=args.timeout)
        out['checks']['override_rpm_202x2'] = (ok3 == 202 and ok4 == 202)

    out['pass'] = all(out['checks'].values()) if out['checks'] else True
    print(json.dumps(out, ensure_ascii=False))

if __name__ == '__main__':
    main()

