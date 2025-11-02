import json, argparse, urllib.request

def get(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8082')
    ap.add_argument('--timeout', type=float, default=6.0)
    args = ap.parse_args()

    out = { 'pass': False, 'missing': [], 'bad_types': [] }
    try:
        j = get(args.base.rstrip('/') + '/api/system/info', args.timeout)
        data = j.get('data', {})
        reg = data.get('registry') or {}
        cache = reg.get('cache')
        if not isinstance(cache, dict):
            out['missing'].append('registry.cache')
        else:
            for k,t in {'enabled':bool,'capacity':int,'idle_ttl_seconds':int,'entries':int}.items():
                if k not in cache:
                    out['missing'].append('registry.cache.'+k)
                else:
                    v = cache[k]
                    if t is int and not isinstance(v, int):
                        out['bad_types'].append(k)
                    if t is bool and not isinstance(v, bool):
                        out['bad_types'].append(k)
        out['pass'] = (len(out['missing'])==0 and len(out['bad_types'])==0)
    except Exception as e:
        out['error'] = str(e)
    print(json.dumps(out, ensure_ascii=False))

if __name__ == '__main__':
    main()

