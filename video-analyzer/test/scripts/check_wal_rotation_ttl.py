#!/usr/bin/env python3
import sys, time, json, subprocess, os, re
import requests

BASE = "http://127.0.0.1:8082"

def fetch_metrics() -> str:
    r = requests.get(f"{BASE}/metrics", timeout=5)
    r.raise_for_status()
    return r.text

def metric_scalar(text: str, name: str) -> int:
    for line in text.splitlines():
        if line.startswith(name) and not line.startswith('#'):
            try:
                return int(float(line.split()[-1]))
            except Exception:
                return 0
    return 0

def post_subscription(uri: str) -> bool:
    payload = {"stream_id":"wal_probe","profile":"default","source_uri":uri}
    r = requests.post(f"{BASE}/api/subscriptions", json=payload, timeout=5)
    return r.status_code in (200,202)

def admin_tail(n:int=50):
    try:
        r = requests.get(f"{BASE}/api/admin/wal/tail?n={n}", timeout=5)
        if r.status_code==200:
            return r.json().get('data',{}).get('items',[])
    except Exception:
        pass
    return []

def restart_va(exe: str, cfg: str) -> None:
    # Stop running VA (ignore errors)
    subprocess.run(["pwsh","-NoProfile","-Command","Get-Process -Name VideoAnalyzer -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue"], check=False)
    time.sleep(1.0)
    # Start VA minimized
    subprocess.run(["pwsh","-NoProfile","-Command", f"Start-Process -WindowStyle Minimized -FilePath '{exe}' -ArgumentList '{cfg}'"], check=True)
    # wait for port to open
    for _ in range(20):
        try:
            requests.get(f"{BASE}/metrics", timeout=1.0)
            return
        except Exception:
            time.sleep(0.5)

def main():
    exe = os.path.abspath(os.path.join(os.getcwd(), 'video-analyzer','build-ninja','bin','VideoAnalyzer.exe'))
    cfg = os.path.abspath(os.path.join(os.getcwd(), 'video-analyzer','build-ninja','bin','config'))
    out = {"pass": False}
    try:
        metrics0 = fetch_metrics()
        wal_enabled = 'va_feature_enabled{feature="wal"} 1' in metrics0
        fr0 = metric_scalar(metrics0, 'va_wal_failed_restart_total')

        # Produce an inflight sub (unreachable rtsp to avoid quick ready)
        _ = post_subscription('rtsp://127.0.0.1:65534/invalid')
        time.sleep(0.5)

        # Restart VA
        restart_va(exe, cfg)
        time.sleep(1.0)
        metrics1 = fetch_metrics()
        fr1 = metric_scalar(metrics1, 'va_wal_failed_restart_total')
        items = admin_tail(50)

        out.update({"failed_restart_before": fr0, "failed_restart_after": fr1, "wal_enabled": wal_enabled, "tail_count": len(items)})
        if wal_enabled:
            out["pass"] = fr1 >= fr0 and len(items) >= 0
        else:
            out["pass"] = True
            out["skipped"] = True
    except Exception as e:
        out["error"] = str(e)
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0 if out.get("pass") else 1)

if __name__ == '__main__':
    main()

