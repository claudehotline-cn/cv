import sys, json, argparse, time, re
import urllib.request

def get(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='ignore')

def has_metric(text, name):
    return ("\n"+name) in ("\n"+text)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8082')
    ap.add_argument('--timeout', type=float, default=5.0)
    args = ap.parse_args()

    out = { 'pass': False, 'missing': [] }
    try:
        txt = get(args.base.rstrip('/') + '/metrics', args.timeout)
        required = [
            'va_quota_dropped_total',
            'va_quota_would_drop_total',
            'va_feature_enabled{feature="quota_observe"}',
            'va_feature_enabled{feature="quota_enforce"}',
            'va_quota_enforce_percent{}'
        ]
        for k in required:
            if k not in txt:
                out['missing'].append(k)
        out['pass'] = (len(out['missing']) == 0)
    except Exception as e:
        out['error'] = str(e)
    print(json.dumps(out, ensure_ascii=False))

if __name__ == '__main__':
    main()

