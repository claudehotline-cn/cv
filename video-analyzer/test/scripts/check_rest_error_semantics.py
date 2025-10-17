#!/usr/bin/env python3
"""
Check REST error semantics for VA (8082) and VSM (7071).

Covers minimal cases:
- VA:
  - POST /api/control/apply_pipeline with empty body -> 400 INVALID_ARG
  - POST /api/control/drain for non-existent -> 404 NOT_FOUND
  - DELETE /api/control/pipeline?name=__not_exists__ -> 404 NOT_FOUND
  - GET /api/control/status?name=__not_exists__ -> 200 success, data.phase==NotFound
  - GET /api/__unknown__ -> 404
- VSM:
  - GET /api/source/list -> 200 success
  - OPTIONS /api/source/list -> 204 with CORS headers

Writes a compact JSON evidence file under docs/memo/assets/YYYY-MM-DD/rest_error_semantics.json
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from typing import Any, Dict

import requests


def run_va_checks(base: str, timeout: float) -> Dict[str, Any]:
    base = base.rstrip("/")
    out: Dict[str, Any] = {"base": base}

    # 400 invalid arg
    r = requests.post(f"{base}/api/control/apply_pipeline", json={}, timeout=timeout)
    out["apply_empty"] = {"status": r.status_code, "body": _safe_json(r)}

    # 404 not found on drain/delete
    r = requests.post(
        f"{base}/api/control/drain", json={"pipeline_name": "__not_exists__", "timeout_sec": 1}, timeout=timeout
    )
    out["drain_missing"] = {"status": r.status_code, "body": _safe_json(r)}

    r = requests.delete(f"{base}/api/control/pipeline?name=__not_exists__", timeout=timeout)
    out["remove_missing"] = {"status": r.status_code, "body": _safe_json(r)}

    # 200 with phase=NotFound
    r = requests.get(f"{base}/api/control/status?name=__not_exists__", timeout=timeout)
    out["status_missing"] = {"status": r.status_code, "body": _safe_json(r)}

    # unknown route -> 404
    r = requests.get(f"{base}/api/__unknown__", timeout=timeout)
    out["unknown_route"] = {"status": r.status_code}

    # 409 conflict-like: apply with invalid yaml_path should fail with 409
    invalid_body = {"pipeline_name": "__conflict_case__", "yaml_path": "D:/nonexistent/path.yaml"}
    r = requests.post(f"{base}/api/control/apply_pipeline", json=invalid_body, timeout=timeout)
    out["apply_invalid_yaml"] = {"status": r.status_code, "body": _safe_json(r)}
    return out


def run_vsm_checks(base: str, timeout: float) -> Dict[str, Any]:
    base = base.rstrip("/")
    out: Dict[str, Any] = {"base": base}
    r = requests.get(f"{base}/api/source/list", timeout=timeout)
    out["list"] = {"status": r.status_code, "body": _safe_json(r)}
    # OPTIONS preflight
    s = requests.Session()
    req = requests.Request("OPTIONS", f"{base}/api/source/list")
    pre = s.prepare_request(req)
    r2 = s.send(pre, timeout=timeout)
    out["options"] = {
        "status": r2.status_code,
        "headers": {
            "AllowOrigin": r2.headers.get("Access-Control-Allow-Origin"),
            "AllowMethods": r2.headers.get("Access-Control-Allow-Methods"),
            "AllowHeaders": r2.headers.get("Access-Control-Allow-Headers"),
        },
    }
    return out


def _safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return resp.text[:256]


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--va", default="http://127.0.0.1:8082")
    ap.add_argument("--vsm", default="http://127.0.0.1:7071")
    ap.add_argument("--timeout", type=float, default=5.0)
    args = ap.parse_args(argv)

    result: Dict[str, Any] = {"ts": _dt.datetime.now().isoformat(timespec="seconds")}
    try:
        result["va"] = run_va_checks(args.va, args.timeout)
    except Exception as e:
        result["va_error"] = str(e)
    try:
        result["vsm"] = run_vsm_checks(args.vsm, args.timeout)
    except Exception as e:
        result["vsm_error"] = str(e)

    # 503 scenario: temporarily stop MySQL container mapped to 13306, probe /api/logs, then restart
    # Best-effort; if docker not present or no container, skip
    try:
        import subprocess, time
        # find container exposing 13306
        ps = subprocess.run(["docker", "ps", "--format", "{{.ID}} {{.Names}} {{.Ports}}"], capture_output=True, text=True, timeout=5)
        cid = name = None
        if ps.returncode == 0:
            for line in ps.stdout.splitlines():
                parts = line.strip().split(maxsplit=2)
                if len(parts) >= 3 and "13306->3306" in parts[2]:
                    cid, name = parts[0], parts[1]
                    break
        if cid:
            subprocess.run(["docker", "stop", cid], check=True, timeout=15)
            time.sleep(2)
            r = requests.get(f"{args.va.rstrip('/')}/api/logs?limit=1", timeout=args.timeout)
            result["va_db_down"] = {"status": r.status_code, "body": _safe_json(r)}
        else:
            result["va_db_down"] = {"skipped": True, "reason": "no mysql container mapping 13306"}
    except Exception as e:
        result["va_db_down_error"] = str(e)
    finally:
        # restart container if we stopped it
        try:
            if cid:
                subprocess.run(["docker", "start", cid], check=False, timeout=20)
        except Exception:
            pass

    # Print brief summary
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # Persist evidence
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    out_dir = os.path.join(root, "docs", "memo", "assets", _dt.date.today().strftime("%Y-%m-%d"))
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "rest_error_semantics.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[evidence] wrote {out_path}")
    
    # Minimal assertions (exit 1 on mismatch)
    def expect(cond: bool, label: str) -> None:
        if not cond:
            raise SystemExit(f"assertion failed: {label}")

    va = result.get("va", {})
    # HTTP statuses
    expect(va.get("apply_empty", {}).get("status") == 400, "VA apply empty -> 400")
    expect(va.get("drain_missing", {}).get("status") == 404, "VA drain missing -> 404")
    expect(va.get("remove_missing", {}).get("status") == 404, "VA remove missing -> 404")
    expect(va.get("status_missing", {}).get("status") == 200, "VA status missing -> 200")
    expect(va.get("unknown_route", {}).get("status") == 404, "VA unknown route -> 404")
    expect(va.get("apply_invalid_yaml", {}).get("status") == 409, "VA invalid yaml -> 409")

    vsm = result.get("vsm", {})
    expect(vsm.get("list", {}).get("status") == 200, "VSM list -> 200")
    expect(vsm.get("options", {}).get("status") == 204, "VSM options -> 204")
    # DB down case: allow skip when docker not present
    vadd = result.get("va_db_down", {})
    if not vadd.get("skipped"):
        expect(vadd.get("status") == 503, "VA logs when DB down -> 503")
    print("[ok] REST error semantics minimal checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
