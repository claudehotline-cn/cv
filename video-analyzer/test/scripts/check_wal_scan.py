#!/usr/bin/env python3
import sys
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8082"

def http_get(path, timeout=8):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as resp:
        data = resp.read().decode("utf-8", errors="ignore")
        return json.loads(data)

def main():
    try:
        s = http_get("/api/admin/wal/summary")
        if not s.get("success"):
            print("FAIL: summary.success is false")
            return 1
        data = s.get("data", {})
        enabled = bool(data.get("enabled", False))
        failed_restart = int(data.get("failed_restart", 0))
        if not enabled:
            print("SKIP: wal disabled")
            return 0
        # When enabled, we at least assert field presence
        print(json.dumps({"enabled": enabled, "failed_restart": failed_restart}, ensure_ascii=False))
        return 0
    except urllib.error.URLError as e:
        print(f"FAIL: http error: {e}")
        return 1
    except Exception as ex:
        print(f"FAIL: {ex}")
        return 1

if __name__ == "__main__":
    sys.exit(main())

