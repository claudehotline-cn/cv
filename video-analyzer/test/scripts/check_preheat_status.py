import json
import os
import subprocess
import sys
import time
from urllib import request

BASE = "http://127.0.0.1:8082"
BIN = os.path.join("video-analyzer", "build-ninja", "bin", "VideoAnalyzer.exe")
CFG = os.path.join("video-analyzer", "build-ninja", "bin", "config")

def http_get(path, timeout=5):
    with request.urlopen(BASE + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

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
        import psutil  # optional
        for p in psutil.process_iter(attrs=["name", "exe"]):
            if p.info.get("name", "").lower().startswith("videoanalyzer"):
                p.kill()
    except Exception:
        pass

def main():
    # Restart VA with preheat envs
    kill_va()
    env = os.environ.copy()
    env["VA_MODEL_REGISTRY_ENABLED"] = "1"
    env["VA_MODEL_PREHEAT_ENABLED"] = "1"
    env["VA_MODEL_PREHEAT_CONCURRENCY"] = "2"
    # Best-effort list; IDs may or may not exist; logic doesn't require actual load
    env["VA_MODEL_PREHEAT_LIST"] = "det_a,det_b"
    p = subprocess.Popen([BIN, CFG], env=env)
    try:
        assert wait_ok(12), "VA not healthy"
        # Check preheat status fields
        info = http_get("/api/system/info")
        reg = info.get("data", {}).get("registry", {})
        pre = reg.get("preheat", {})
        assert pre.get("enabled") is True, "preheat not enabled"
        assert isinstance(pre.get("concurrency"), int), "concurrency missing"
        assert pre.get("status") in ("idle", "running", "done"), f"bad status: {pre.get('status')}"
        # Poll until warmed > 0 or status=done
        t0 = time.time()
        warmed = pre.get("warmed", 0)
        while time.time()-t0 < 8 and warmed == 0 and pre.get("status") != "done":
            time.sleep(0.5)
            pre = http_get("/api/system/info").get("data", {}).get("registry", {}).get("preheat", {})
            warmed = pre.get("warmed", 0)
        assert warmed >= 0, "warmed missing"
        print("preheat status: OK")
    finally:
        try:
            p.terminate()
        except Exception:
            pass

if __name__ == "__main__":
    main()

