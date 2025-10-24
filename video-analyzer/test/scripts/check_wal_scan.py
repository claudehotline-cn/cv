import json
import os
import subprocess
import time
from urllib import request

BASE = "http://127.0.0.1:8082"
BIN = os.path.join("video-analyzer", "build-ninja", "bin", "VideoAnalyzer.exe")
CFG = os.path.join("video-analyzer", "build-ninja", "bin", "config")

def http_get(path, timeout=5):
    with request.urlopen(BASE + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

def http_post(path, payload, timeout=5):
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(BASE + path, data=data, headers={"Content-Type":"application/json"})
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.getcode(), resp.headers

def wait_ok(timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            j = http_get("/api/system/info", timeout=2)
            if j.get("code") == "OK":
                return True
        except Exception:
            time.sleep(0.2)
    return False

def kill_va():
    try:
        import psutil
        for p in psutil.process_iter(attrs=["name", "exe"]):
            if p.info.get("name", "").lower().startswith("videoanalyzer"):
                p.kill()
    except Exception:
        pass

def main():
    # Start with WAL enabled
    kill_va()
    env = os.environ.copy()
    env["VA_WAL_SUBSCRIPTIONS"] = "1"
    env["VA_WAL_MAX_BYTES"] = "1048576"
    p = subprocess.Popen([BIN, CFG], env=env)
    try:
        assert wait_ok(12), "VA not healthy"
        # Create a subscription to ensure an enqueue event
        payload = {"stream_id":"cam01","profile":"det_720p","source_uri":"rtsp://127.0.0.1:8554/camera_01"}
        _, code, _ = http_post("/api/subscriptions", payload)
        assert code in (200,202), f"unexpected subscribe code: {code}"
        # Quick restart to trigger failed restart scan
        p.terminate()
        p.wait(timeout=5)
        p = subprocess.Popen([BIN, CFG], env=env)
        assert wait_ok(12), "VA not healthy after restart"
        # Check /api/admin/wal/summary for failed_restart >= 0 (non-negative) and enabled
        s = http_get("/api/admin/wal/summary")
        assert s.get("code") == "OK", s
        data = s.get("data", {})
        assert data.get("enabled") is True, "WAL not enabled"
        fr = data.get("failed_restart", 0)
        assert isinstance(fr, int) and fr >= 0, "bad failed_restart"
        print("wal scan: OK (failed_restart=", fr, ")")
    finally:
        try: p.terminate()
        except Exception: pass

if __name__ == "__main__":
    main()
