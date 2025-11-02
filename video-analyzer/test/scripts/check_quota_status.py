import sys, json, argparse, time
import urllib.request

def get(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode('utf-8')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8082')
    ap.add_argument('--timeout', type=float, default=5.0)
    args = ap.parse_args()

    out = { 'pass': False, 'missing': [], 'values': {} }
    try:
        raw = get(args.base.rstrip('/') + '/api/system/info', args.timeout)
        j = json.loads(raw)
        data = j.get('data', {})
        quotas = data.get('quotas')
        if not isinstance(quotas, dict):
            out['missing'].append('quotas')
        else:
            # required keys
            keys = ['enabled','header_key','observe_only','enforce_percent','default','global','acl','exempt_keys','key_overrides']
            for k in keys:
                if k not in quotas:
                    out['missing'].append('quotas.'+k)
            out['values'] = {
                'enabled': quotas.get('enabled'),
                'enforce_percent': quotas.get('enforce_percent'),
                'exempt_count': len(quotas.get('exempt_keys', [])),
                'override_count': len(quotas.get('key_overrides', [])),
            }
        out['pass'] = (len(out['missing']) == 0)
    except Exception as e:
        out['error'] = str(e)
    print(json.dumps(out, ensure_ascii=False))

if __name__ == '__main__':
    main()

