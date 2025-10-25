#!/usr/bin/env python3
import json, sys, os
from urllib import request, error

BASE = os.environ.get("CP_BASE_URL", "http://127.0.0.1:8080")

def main():
    try:
        with request.urlopen(BASE+"/api/system/info", timeout=5) as resp:
            body = resp.read().decode('utf-8', errors='ignore')
            data = json.loads(body)
            restream = data.get('data',{}).get('restream',{})
            assert 'rtsp_base' in restream, 'missing restream.rtsp_base'
            print('PASS')
            return 0
    except Exception as ex:
        print('FAIL:', ex)
        return 1

if __name__ == '__main__':
    sys.exit(main())

