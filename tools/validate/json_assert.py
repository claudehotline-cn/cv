#!/usr/bin/env python3
import sys, json, argparse

def parse_expect(e):
    # format: path[:type][=value]
    path, tp, val = e, None, None
    if ':' in path:
        path, rest = path.split(':', 1)
        if '=' in rest:
            tp, val = rest.split('=', 1)
        else:
            tp = rest
    elif '=' in path:
        path, val = path.split('=', 1)
    return path.split('.'), tp, val

def get(obj, keys):
    cur = obj
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            raise KeyError('.'.join(keys))
    return cur

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--expect', action='append', required=True, help='path[:type][=value] e.g. data.provider or data.gpu_active:bool')
    args = ap.parse_args()
    try:
        obj = json.load(sys.stdin)
    except Exception as ex:
        print('{"error":"invalid_json","msg":"%s"}' % ex, file=sys.stderr)
        return 1
    for e in args.expect:
        keys, tp, val = parse_expect(e)
        try:
            v = get(obj, keys)
        except KeyError:
            print('{"error":"missing","path":"%s"}' % '.'.join(keys))
            return 2
        if tp:
            if tp == 'int' and not isinstance(v, int):
                print('{"error":"type","path":"%s","want":"int"}' % '.'.join(keys))
                return 3
            if tp == 'bool' and not isinstance(v, bool):
                print('{"error":"type","path":"%s","want":"bool"}' % '.'.join(keys))
                return 3
            if tp == 'str' and not isinstance(v, str):
                print('{"error":"type","path":"%s","want":"str"}' % '.'.join(keys))
                return 3
        if val is not None:
            if isinstance(v, bool):
                cmp = 'true' if v else 'false'
            else:
                cmp = str(v)
            if cmp != val:
                print('{"error":"value","path":"%s","want":"%s","got":"%s"}' % ('.'.join(keys), val, cmp))
                return 4
    print('{"code":"OK"}')
    return 0

if __name__ == '__main__':
    sys.exit(main())

