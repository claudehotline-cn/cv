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
    ap.add_argument('--timeout', type=float, default=8.0)
    ap.add_argument('--poll-interval', type=float, default=0.3)
    args = ap.parse_args()

    base = args.base.rstrip('/')
    out = { 'pass': False }
    try:
        bad_model = 'model_nonexistent_' + str(int(time.time()*1000))
        key = 'failload_' + str(int(time.time()*1000))
        code, body, hdrs = post_json(base + '/api/subscriptions', {
            'stream_id': 'fail_model_'+str(int(time.time()*1000)),
            'profile': 'det_720p',
            'source_uri': 'rtsp://127.0.0.1:8554/camera_01',
            'model_id': bad_model
        }, timeout=4.0, headers={'X-API-Key': key})
        if code not in (200, 202):
            out['error'] = f'create status {code}'
            print(json.dumps(out, ensure_ascii=False)); return
        try:
            j = json.loads(body)
            sid = j.get('data',{}).get('id')
        except Exception:
            sid = None
        if not sid:
            loc = hdrs.get('Location') or hdrs.get('location') or ''
            if loc.rfind('/')>=0:
                sid = loc.rsplit('/',1)[-1]
        if not sid:
            out['error'] = 'no id'
            print(json.dumps(out, ensure_ascii=False)); return
        deadline = time.time() + args.timeout
        phase=None; reason=''
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
        out['pass'] = (phase == 'failed' and (('model' in reason.lower()) or ('load' in reason.lower()) or ('no model resolved' in reason.lower()) or ('subscribe_failed' in reason.lower())))
    except Exception as e:
        out['error'] = str(e)
    print(json.dumps(out, ensure_ascii=False))

if __name__ == '__main__':
    main()
