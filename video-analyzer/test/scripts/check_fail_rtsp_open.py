import json, time, argparse, urllib.request, urllib.error

def post_json(url, data, timeout=6.0, headers=None):
    body = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json', **(headers or {})}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.getcode(), r.read().decode('utf-8'), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='ignore'), dict(e.headers)

def get_json(url, timeout=6.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8082')
    ap.add_argument('--timeout', type=float, default=10.0)
    ap.add_argument('--poll-interval', type=float, default=0.4)
    args = ap.parse_args()

    base = args.base.rstrip('/')
    out = { 'pass': False }
    # Use an unreachable RTSP port/path to trigger open failure
    bad_rtsp = 'rtsp://127.0.0.1:65534/invalid_path'
    try:
        # random key to avoid per-key rpm/concurrent collisions
        key = 'failopen_' + str(int(time.time()*1000))
        code, body, hdrs = post_json(base + '/api/subscriptions', {
            'stream_id': 'fail_open_'+str(int(time.time()*1000)),
            'profile': 'default',
            'source_uri': bad_rtsp
        }, timeout=4.0, headers={'X-API-Key': key})
        # Fast-pass when ACL 拒绝（例如 scheme 不允许）
        if code in (401,403):
            qr = (hdrs.get('X-Quota-Reason') or hdrs.get('x-quota-reason') or '')
            if qr.startswith('acl_'):
                out['phase'] = 'failed'
                out['reason'] = qr
                out['pass'] = True
                print(json.dumps(out, ensure_ascii=False)); return
        if code not in (200, 202):
            out['error'] = f'create status {code}'
            print(json.dumps(out, ensure_ascii=False)); return
        # Parse id from body JSON
        try:
            j = json.loads(body)
            sid = j.get('data',{}).get('id')
        except Exception:
            sid = None
        if not sid:
            # fallback: from Location header
            loc = hdrs.get('Location') or hdrs.get('location') or ''
            if loc.rfind('/')>=0:
                sid = loc.rsplit('/',1)[-1]
        if not sid:
            out['error'] = 'no id'
            print(json.dumps(out, ensure_ascii=False)); return

        # poll status
        deadline = time.time() + max(args.timeout, 60.0)
        phase = None; reason = ''
        while time.time() < deadline:
            s = get_json(f"{base}/api/subscriptions/{sid}?include=timeline", timeout=3.0)
            d = s.get('data', {})
            phase = d.get('phase')
            reason = d.get('reason','') or ''
            if phase in ('failed','cancelled','ready'):
                break
            time.sleep(args.poll_interval)
        out['phase'] = phase
        out['reason'] = reason
        out['pass'] = (phase == 'failed' and (('rtsp' in reason.lower()) or ('open' in reason.lower()) or ('timeout' in reason.lower()) or ('subscribe_failed' in reason.lower())))
    except Exception as e:
        out['error'] = str(e)
    print(json.dumps(out, ensure_ascii=False))

if __name__ == '__main__':
    main()
