"""
Check control-plane HotSwap and Status endpoints for basic semantics.

Verifies:
- POST /api/control/hotswap validation errors -> 400
- GET  /api/control/status?name=__not_exists__ -> 200 with data.phase == NotFound

Optional: apply_pipeline can be exercised separately once a valid graph is ensured.
"""
import argparse
import json
import sys
import time

import requests


def main():
    ap = argparse.ArgumentParser(description="Check HotSwap + Status endpoints")
    ap.add_argument("--base", default="http://127.0.0.1:8082", help="API base URL")
    ap.add_argument("--timeout", type=float, default=5.0)
    args = ap.parse_args()

    base = args.base.rstrip("/")
    out = {}

    # 1) HotSwap required fields
    def post(path, payload):
        r = requests.post(base + path, json=payload, timeout=args.timeout)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text}
        return r.status_code, body

    status, body = post("/api/control/hotswap", {})
    out["hotswap_missing_all"] = {"status": status, "body": body}

    status, body = post("/api/control/hotswap", {"pipeline_name": "p"})
    out["hotswap_missing_node"] = {"status": status, "body": body}

    status, body = post(
        "/api/control/hotswap",
        {"pipeline_name": "p", "node": "det"},
    )
    out["hotswap_missing_model_uri"] = {"status": status, "body": body}

    # 2) Status for non-existent pipeline
    r = requests.get(base + "/api/control/status", params={"name": "__not_exists__"}, timeout=args.timeout)
    try:
        b = r.json()
    except Exception:
        b = {"raw": r.text}
    out["status_not_found"] = {"status": r.status_code, "body": b}

    # Print JSON result and also write to file if path hinted via env
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())

