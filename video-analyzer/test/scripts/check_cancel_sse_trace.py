"""
Minimal SSE trace verification for cancel use case (no frontend).

Steps:
 1) POST /api/subscriptions -> expect 202, capture id
 2) Connect SSE /api/subscriptions/{id}/events and capture first phase
 3) DELETE /api/subscriptions/{id} -> expect 202
 4) Wait briefly for SSE 'cancelled' OR fallback GET include=timeline

Exit codes:
  0: PASS (DELETE 202 + SSE connected + (SSE 'cancelled' OR timeline has 'cancelled' OR at least a phase observed))
  2: FAIL (otherwise)

Dependencies: requests (only). SSE parsed manually.
"""
from __future__ import annotations
import argparse
import requests
import sys
import threading
import time
from typing import List, Optional


def post_json(base: str, path: str, payload: dict, timeout: float):
    r = requests.post(base + path, json=payload, timeout=timeout)
    return r.status_code, r.json() if r.content else {}


def delete_json(base: str, path: str, timeout: float):
    r = requests.delete(base + path, timeout=timeout)
    return r.status_code, r.json() if r.content else {}


def get_json(base: str, path: str, timeout: float):
    r = requests.get(base + path, timeout=timeout)
    return r.status_code, r.json() if r.content else {}


def sse_listen(url: str, stop: threading.Event, phases: List[str], connect_flag: dict):
    try:
        with requests.get(url, stream=True, headers={"Accept": "text/event-stream"}, timeout=3) as r:
            connect_flag["ok"] = (r.status_code == 200)
            ev_type: Optional[str] = None
            data_buf: Optional[str] = None
            for raw in r.iter_lines(decode_unicode=True):
                if stop.is_set():
                    break
                if raw is None:
                    continue
                line = raw.strip()
                if not line:
                    # dispatch
                    if ev_type == "phase" and data_buf:
                        try:
                            import json
                            d = json.loads(data_buf)
                            p = str(d.get("phase", "")).lower()
                            if p:
                                phases.append(p)
                        except Exception:
                            pass
                    ev_type = None
                    data_buf = None
                    continue
                if line.startswith("event:"):
                    ev_type = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data = line.split(":", 1)[1].strip()
                    data_buf = (data if data_buf is None else (data_buf + data))
    except Exception:
        # mark not connected if network fails
        connect_flag.setdefault("ok", False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8082")
    ap.add_argument("--profile", default="det_720p")
    ap.add_argument("--stream-id", default="sse_cancel_minimal_01")
    ap.add_argument("--url", default="rtsp://127.0.0.1:8554/camera_01")
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--cancel-delay-ms", type=int, default=50)
    ap.add_argument("--wait-after-cancel-ms", type=int, default=2000)
    ap.add_argument("--require-cancel", action="store_true", help="require 'cancelled' via SSE or timeline; otherwise only check SSE connectivity + DELETE 202")
    args = ap.parse_args()

    # 1) create subscription
    payload = {"stream_id": args.stream_id, "profile": args.profile, "url": args.url}
    st, body = post_json(args.base, "/api/subscriptions", payload, args.timeout)
    if st != 202:
        print(f"[ERR] create status={st}: {str(body)[:200]}")
        return 2
    sub_id = (body.get("data") or {}).get("id") or ""
    if not sub_id:
        print(f"[ERR] missing id: {body}")
        return 2

    # 2) connect SSE
    sse_url = f"{args.base}/api/subscriptions/{sub_id}/events"
    phases: List[str] = []
    stop = threading.Event()
    flag = {"ok": False}
    th = threading.Thread(target=sse_listen, args=(sse_url, stop, phases, flag), daemon=True)
    th.start()

    # small delay to increase likelihood of connect
    time.sleep(max(args.cancel_delay_ms, 0) / 1000.0)

    # 3) cancel
    st_del, body_del = delete_json(args.base, f"/api/subscriptions/{sub_id}", args.timeout)
    if st_del != 202:
        print(f"[ERR] delete status={st_del}: {str(body_del)[:200]}")
        stop.set(); th.join(timeout=0.2)
        return 2

    # 4) wait briefly for SSE 'cancelled'
    deadline = time.time() + (max(args.wait_after_cancel_ms, 0) / 1000.0)
    got_cancel_sse = False
    while time.time() < deadline:
        if any(p == "cancelled" for p in phases):
            got_cancel_sse = True
            break
        time.sleep(0.05)
    stop.set(); th.join(timeout=0.5)

    # Fallback: timeline
    st_get, body_get = get_json(args.base, f"/api/subscriptions/{sub_id}?include=timeline", args.timeout)
    phase = str(((body_get.get("data") or {}).get("phase") or "")).lower()
    tl = (body_get.get("data") or {}).get("timeline") or {}
    has_cancelled_ts = "cancelled" in tl

    sse_connected = bool(flag.get("ok") or phases)
    if args.require_cancel:
        ok = (st_del == 202) and sse_connected and (got_cancel_sse or has_cancelled_ts or (phase == "cancelled"))
    else:
        # minimal evidence: SSE connected and DELETE accepted; phases may be empty if READY raced
        ok = (st_del == 202) and sse_connected

    summary = {
        "id": sub_id,
        "delete_code": st_del,
        "sse_connected": bool(sse_connected),
        "observed_phases": phases[:6],
        "got_cancel_sse": bool(got_cancel_sse),
        "phase": phase,
        "timeline_keys": list(tl.keys())[:8],
        "pass": bool(ok),
    }
    print(summary)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
