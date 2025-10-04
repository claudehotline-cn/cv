#!/usr/bin/env python3
"""
Auto test script for VideoAnalyzer backend.

Features
- Sets engine mode (IoBinding pinned / GPU no IoBinding / CPU)
- Subscribes a stream to an RTSP source
- Polls pipelines until frames are processed or timeout
- Dumps runtime flags and recent logs on failure

Usage examples
  python auto_test_pipeline.py \
    --base http://127.0.0.1:8082 \
    --stream-id camera_01 \
    --profile det_720p \
    --rtsp rtsp://127.0.0.1:8554/camera_01 \
    --mode iobinding_pinned \
    --timeout-sec 45

Modes
  iobinding_pinned  -> use_io_binding=true + prefer_pinned=true + disable device staging
  gpu_no_iobind     -> use_io_binding=false, provider=cuda
  cpu               -> use_io_binding=false, provider=cpu

Exit codes
  0  success (frames processed)
  1  HTTP/transport error
  2  timeout (no frames)
  3  server reported error
"""

import argparse
import json
import sys
import time
from urllib import request, error
from urllib.parse import urljoin
from pathlib import Path


def http_json(method: str, url: str, payload: dict | None = None, timeout: int = 10) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if body.strip():
                return json.loads(body)
            return {}
    except error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
            return json.loads(body)
        except Exception:
            raise


def get_text(url: str, timeout: int = 8) -> str:
    with request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def set_engine(base: str, mode: str,
               host_pool_bytes: int = 8*1024*1024,
               device_pool_bytes: int = 0,
               io_binding_input_bytes: int = 0,
               io_binding_output_bytes: int = 0,
               device: int = 0) -> dict:
    opts: dict = {
        "use_io_binding": mode == "iobinding_pinned",
        "prefer_pinned_memory": mode == "iobinding_pinned",
        "allow_cpu_fallback": True,
        "enable_profiling": False,
        "trt_fp16": False,
        "trt_int8": False,
        "trt_workspace_mb": 0,
        "io_binding_input_bytes": int(io_binding_input_bytes),
        "io_binding_output_bytes": int(io_binding_output_bytes),
        "tensor_host_pool_bytes": int(host_pool_bytes),
        # 禁用设备侧输入 staging（为避免 CUDA invalid argument）
        "tensor_device_pool_bytes": int(device_pool_bytes if mode != "iobinding_pinned" else 0),
    }
    provider = "cpu" if mode == "cpu" else "cuda"
    payload = {
        "type": f"ort-{provider}",
        "provider": provider,
        "device": int(device),
        "options": opts,
    }
    return http_json("POST", urljoin(base, "/engine/set"), payload)


def unsubscribe(base: str, stream_id: str, profile: str) -> None:
    try:
        http_json("POST", urljoin(base, "/unsubscribe"), {
            "stream_id": stream_id,
            "profile": profile,
        })
    except Exception:
        pass


def subscribe(base: str, stream_id: str, profile: str, rtsp: str) -> dict:
    return http_json("POST", urljoin(base, "/subscribe"), {
        "stream_id": stream_id,
        "profile": profile,
        "source_uri": rtsp,
    })


def get_system_info(base: str) -> dict:
    return http_json("GET", urljoin(base, "/system/info"))


def get_pipelines(base: str) -> dict:
    return http_json("GET", urljoin(base, "/pipelines"))


def find_repo_root(start: Path) -> Path:
    cur = start.resolve()
    for _ in range(6):
        if (cur / "video-analyzer").exists():
            return cur
        cur = cur.parent
    return start.resolve()


def read_log_candidates(repo_root: Path) -> list[str]:
    out: list[str] = []
    # Primary exe log (build/Release)
    out.append(str(repo_root / "video-analyzer" / "build" / "bin" / "Release" / "logs" / "video-analyzer.log"))
    # Root error log
    out.append(str(repo_root / "logs" / "error.log"))
    return out


def tail_file(path: Path, lines: int = 120) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            data = f.read()
        parts = data.splitlines()
        return "\n".join(parts[-lines:])
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Automated E2E test for VideoAnalyzer")
    ap.add_argument("--base", default="http://127.0.0.1:8082")
    ap.add_argument("--stream-id", default="camera_01")
    ap.add_argument("--profile", default="det_720p")
    ap.add_argument("--rtsp", default="rtsp://127.0.0.1:8554/camera_01")
    ap.add_argument("--mode", choices=["iobinding_pinned", "gpu_no_iobind", "cpu"], default="iobinding_pinned")
    ap.add_argument("--timeout-sec", type=int, default=45)
    ap.add_argument("--expect-frames", type=int, default=1)
    ap.add_argument("--host-pool-bytes", type=int, default=8*1024*1024)
    ap.add_argument("--device-pool-bytes", type=int, default=0)
    ap.add_argument("--io-in-bytes", type=int, default=0)
    ap.add_argument("--io-out-bytes", type=int, default=0)
    args = ap.parse_args()

    try:
        print("[1/5] Setting engine...")
        resp1 = set_engine(args.base, args.mode,
                           host_pool_bytes=args.host_pool_bytes,
                           device_pool_bytes=args.device_pool_bytes,
                           io_binding_input_bytes=args.io_in_bytes,
                           io_binding_output_bytes=args.io_out_bytes,
                           device=0)
        if not resp1 or not resp1.get("success", True):
            print("Engine set failed:", resp1)
            return 3

        print("[2/5] Unsubscribe (cleanup)...")
        unsubscribe(args.base, args.stream_id, args.profile)

        print("[3/5] Subscribe stream...")
        resp2 = subscribe(args.base, args.stream_id, args.profile, args.rtsp)
        if not resp2 or not resp2.get("success", False):
            print("Subscribe failed:", resp2)
            return 3

        print("[4/5] Polling pipelines for frames...")
        deadline = time.time() + args.timeout_sec
        processed = 0
        last_fps = 0.0
        while time.time() < deadline:
            time.sleep(2.0)
            pipes = get_pipelines(args.base)
            data = pipes.get("data") or []
            if data:
                # find matching pipeline
                pl = None
                for item in data:
                    if item.get("stream_id") == args.stream_id and item.get("profile_id") == args.profile:
                        pl = item
                        break
                if pl:
                    m = pl.get("metrics") or {}
                    processed = int(m.get("processed_frames") or 0)
                    last_fps = float(m.get("fps") or 0.0)
                    print(f"  metrics: frames={processed} fps={last_fps:.2f}")
                    if processed >= args.expect_frames:
                        break

        print("[5/5] Runtime snapshot...")
        sysinfo = get_system_info(args.base)
        print(json.dumps(sysinfo, indent=2, ensure_ascii=False))

        if processed < args.expect_frames:
            print("\n[FAIL] No frames processed within timeout.")
            # dump logs
            repo_root = find_repo_root(Path(__file__).resolve().parent)
            for p in read_log_candidates(repo_root):
                content = tail_file(Path(p), 200)
                if content:
                    print(f"\n--- tail {p} ---\n{content}")
            print("\nHints:")
            print("- Ensure RTSP is publishing at", args.rtsp)
            print("- If CUDA invalid argument appears, try --mode cpu or --mode gpu_no_iobind")
            return 2

        print("\n[PASS] Frames processed:", processed, "fps:", f"{last_fps:.2f}")
        return 0

    except Exception as ex:
        print("[ERROR] Test execution failed:", ex)
        try:
            repo_root = find_repo_root(Path(__file__).resolve().parent)
            for p in read_log_candidates(repo_root):
                content = tail_file(Path(p), 120)
                if content:
                    print(f"\n--- tail {p} ---\n{content}")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())

