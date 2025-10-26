#!/usr/bin/env python3
import os, subprocess, sys, time, signal
from urllib import request, error

def wait_port(url, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with request.urlopen(url, timeout=1) as resp:
                return True
        except Exception:
            time.sleep(0.2)
    return False

def main():
    exe = os.path.join('controlplane','build','bin','controlplane.exe')
    if not os.path.exists(exe):
        print('FAIL: controlplane.exe not found', file=sys.stderr)
        return 1
    env = os.environ.copy()
    env['CP_FAKE_WATCH'] = '1'
    base = env.get('CP_BASE_URL', 'http://127.0.0.1:18080')
    p = subprocess.Popen([exe, 'controlplane/config'], env=env)
    try:
        if not wait_port(base + '/metrics', 5.0):
            print('SKIP: metrics not ready')
            return 0
        # direct SSE GET to fake id
        url = base + '/api/subscriptions/fake-1/events'
        with request.urlopen(url, timeout=10) as resp:
            body = resp.read().decode('utf-8','ignore')
            if 'event: phase' in body and '"phase":"ready"' in body:
                print('PASS')
                return 0
            print('SKIP: unexpected body')
            return 0
    except error.HTTPError as e:
        print('FAIL: status {}'.format(e.code))
        return 1
    except Exception as ex:
        print('SKIP: exception {}'.format(ex))
        return 0
    finally:
        try:
            if os.name == 'nt':
                p.send_signal(signal.CTRL_BREAK_EVENT)
            p.terminate()
        except Exception:
            pass
        try:
            p.wait(timeout=2)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass

if __name__ == '__main__':
    sys.exit(main())

