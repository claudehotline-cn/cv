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
        summary = http_get("/api/admin/wal/summary")
        if not summary.get("success"):
            print("FAIL: summary.success is false")
            return 1
        enabled = bool(summary.get("data", {}).get("enabled", False))
        # Tail always available as read-only; enabled controls append behavior
        tail = http_get("/api/admin/wal/tail?n=50")
        if not tail.get("success"):
            print("FAIL: tail.success is false")
            return 1
        items = tail.get("data", {}).get("items", [])
        print(json.dumps({
            "enabled": enabled,
            "count": len(items)
        }, ensure_ascii=False))
        return 0
    except urllib.error.URLError as e:
        print(f"FAIL: http error: {e}")
        return 1
    except Exception as ex:
        print(f"FAIL: {ex}")
        return 1

if __name__ == "__main__":
    sys.exit(main())

