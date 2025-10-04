#!/usr/bin/env python3
"""
Run a 3-mode test matrix against the VideoAnalyzer backend.

It sequentially runs auto_test_pipeline.py with modes:
  1) iobinding_pinned
  2) gpu_no_iobind
  3) cpu

It summarizes each run's exit code and key output.

Usage:
  python video-analyzer/test/auto_test_matrix.py \
    --base http://127.0.0.1:8082 \
    --stream-id camera_01 \
    --profile det_720p \
    --rtsp rtsp://127.0.0.1:8554/camera_01 \
    --timeout-sec 45 --expect-frames 1

Exit codes:
  0 if any mode passes
  1 if a transport/HTTP error occurred in any run (and no pass)
  2 if all runs time out without frames
  3 generic failure
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def default_python() -> str:
    return sys.executable or "python"


def find_pipeline_script(start: Path) -> Path:
    # Prefer sibling auto_test_pipeline.py
    p = (start / "auto_test_pipeline.py").resolve()
    if p.exists():
        return p
    # Try discovery from repo root
    cur = start.resolve()
    for _ in range(6):
        candidate = cur / "video-analyzer" / "test" / "auto_test_pipeline.py"
        if candidate.exists():
            return candidate
        cur = cur.parent
    return p  # may not exist; subprocess will fail clearly


def run_one(python: str, script: Path, base: str, stream_id: str, profile: str,
            rtsp: str, mode: str, timeout_sec: int, expect_frames: int,
            host_pool_bytes: int, device_pool_bytes: int,
            io_in_bytes: int, io_out_bytes: int) -> tuple[int, str]:
    cmd = [python, str(script),
           "--base", base,
           "--stream-id", stream_id,
           "--profile", profile,
           "--rtsp", rtsp,
           "--mode", mode,
           "--timeout-sec", str(timeout_sec),
           "--expect-frames", str(expect_frames),
           "--host-pool-bytes", str(host_pool_bytes),
           "--device-pool-bytes", str(device_pool_bytes),
           "--io-in-bytes", str(io_in_bytes),
           "--io-out-bytes", str(io_out_bytes)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        out = (proc.stdout or "") + ("\nSTDERR:\n" + proc.stderr if proc.stderr else "")
        return proc.returncode, out
    except Exception as ex:
        return 1, f"[runner] failed to start: {ex}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Run 3-mode matrix tests")
    ap.add_argument("--base", default="http://127.0.0.1:8082")
    ap.add_argument("--stream-id", default="camera_01")
    ap.add_argument("--profile", default="det_720p")
    ap.add_argument("--rtsp", default="rtsp://127.0.0.1:8554/camera_01")
    ap.add_argument("--timeout-sec", type=int, default=45)
    ap.add_argument("--expect-frames", type=int, default=1)
    ap.add_argument("--python", default=default_python())
    ap.add_argument("--script", default="")
    # Advanced pool knobs
    ap.add_argument("--host-pool-bytes", type=int, default=8*1024*1024)
    ap.add_argument("--device-pool-bytes", type=int, default=0)
    ap.add_argument("--io-in-bytes", type=int, default=0)
    ap.add_argument("--io-out-bytes", type=int, default=0)
    args = ap.parse_args()

    script_path = Path(args.script) if args.script else find_pipeline_script(Path(__file__).resolve().parent)
    if not script_path.exists():
        print("auto_test_pipeline.py not found at:", script_path, file=sys.stderr)
        return 3

    print("Using Python:", args.python)
    print("Pipeline script:", script_path)
    print()

    modes = [
        "iobinding_pinned",
        "gpu_no_iobind",
        "cpu",
    ]

    results: list[tuple[str, int, str]] = []
    worst_code = 3

    for mode in modes:
        print(f"===== Running mode: {mode} =====")
        code, out = run_one(
            args.python,
            script_path,
            args.base,
            args.stream_id,
            args.profile,
            args.rtsp,
            mode,
            args.timeout_sec,
            args.expect_frames,
            args.host_pool_bytes,
            args.device_pool_bytes,
            args.io_in_bytes,
            args.io_out_bytes,
        )
        print(out)
        print(f"===== Result {mode}: exit={code} =====\n")
        results.append((mode, code, out))
        if code == 0:
            worst_code = 0
        elif worst_code != 0 and code == 1:
            worst_code = 1
        elif worst_code not in (0, 1) and code == 2:
            worst_code = 2

    print("\n==== Summary ====")
    for mode, code, _ in results:
        print(f"{mode:16s} -> exit {code}")

    return worst_code


if __name__ == "__main__":
    sys.exit(main())

