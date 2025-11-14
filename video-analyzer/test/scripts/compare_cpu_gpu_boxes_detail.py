#!/usr/bin/env python3
"""
Compare YOLO detection box counts between a "CPU-like" path and a "GPU/Iobinding" path.

本脚本基于 VA 的 REST 接口与日志输出，对比同一条流在两种引擎配置下的检测框数量差异：

- CPU 模式：io_binding + device_output_views=False + stage_device_outputs=True + CPU NMS
- GPU 模式：io_binding + device_output_views=True  + stage_device_outputs=False + CUDA NMS

注意：
- 当前 VA 并未直接暴露每帧的 boxes 明细给外部 API，因此脚本通过解析 ms.nms 日志中的 "boxes=<N>" 行
  作为近似指标来衡量两种路径的检测框数量差异。
- 若需要进一步比对坐标级别的差异，需要在 VA 侧新增更详细的调试日志或专用 API。

用法示例：
  python compare_cpu_gpu_boxes_detail.py \\
      --base http://127.0.0.1:8082 \\
      --rtsp rtsp://127.0.0.1:8554/camera_01 --profile det_720p \\
      --duration-sec 15 --warmup-sec 3
"""
from __future__ import annotations

import argparse
import os
import re
import time
import uuid
from statistics import median, mean
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests import HTTPError


def _get(base: str, path: str, timeout: float) -> Dict[str, Any]:
    r = requests.get(base + path, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    return j if isinstance(j, dict) else {"success": False}


def _post(base: str, path: str, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    r = requests.post(base + path, json=payload, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    return j if isinstance(j, dict) else {"success": False}


def set_engine(base: str, engine_type: str, opts: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    """
    Try to set engine via VA 本机 REST 或经由 CP 代理：
      1) POST /api/engine/set    （VA 直接暴露 REST）
      2) POST /api/control/set_engine （通过 ControlPlane 转发到 VA）
    """
    payload = {
        "type": engine_type,
        "device": 0,
        "options": {k: ("true" if v is True else "false" if v is False else v) for k, v in opts.items()},
    }
    last: Optional[Exception] = None
    paths = ["/api/engine/set", "/api/control/set_engine"]
    for _ in range(3):
        for path in paths:
            try:
                j = _post(base, path, payload, timeout)
                # CP `/api/control/set_engine` 回包形如 {"code":"OK", "data":{...}}
                if path == "/api/control/set_engine":
                    if j.get("code") == "OK":
                        return j
                    last = RuntimeError(f"control/set_engine returned {j}")
                    continue
                # VA `/api/engine/set` 回包形如 {"success": true, ...}
                if not j.get("success", False):
                    last = RuntimeError(f"engine/set returned {j}")
                    continue
                return j
            except HTTPError as he:
                # 404 / 405 等视为该路径不可用，继续尝试下一个
                last = he
                # no sleep here; we just try next path
                continue
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(0.5)
        # 一轮路径均失败后稍作等待再重试
        time.sleep(0.5)
    raise last  # type: ignore[misc]


def wait_ready(base: str, timeout: float, max_wait: float = 6.0) -> bool:
    end = time.time() + max_wait
    while time.time() < end:
        try:
            r = requests.get(base + "/api/system/info", timeout=timeout)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def unsubscribe_cp(base: str, sub_id: str, timeout: float) -> None:
    """
    通过 CP 的 LRO 接口删除订阅资源：DELETE /api/subscriptions/{id}
    """
    import requests  # local import to avoid exposing globally

    try:
        r = requests.delete(base + f"/api/subscriptions/{sub_id}", timeout=timeout)
        # 202/200 都视为成功，其余仅记录不抛异常
        _ = r.status_code
    except Exception:
        pass


def pick_log_file(base: str, timeout: float) -> Optional[str]:
    """Try to discover VA release log file path via /api/logging, fallback to common paths."""
    try:
        j = _get(base, "/api/logging", timeout)
        if j.get("success"):
            data = j.get("data", {})
            p = data.get("file_path")
            if p and os.path.isfile(p):
                return p
    except Exception:
        pass
    # fallback to repo default path
    candidates = [
        os.path.join("logs", "video-analyzer-release.log"),
        os.path.join("video-analyzer", "logs", "video-analyzer-release.log"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def tail_boxes_series(path: str, start_size: int, interval_s: float, seconds: float) -> List[Tuple[int, str]]:
    """
    Tail ms.nms logs and extract a time series of "boxes=<N>" values.
    We only look at new bytes after start_size, over a limited time window.
    """
    if not path:
        return []
    series: List[Tuple[int, str]] = []
    pat = re.compile(r"ms\.nms.*boxes=(\d+)")
    end = time.time() + seconds
    pos = start_size if start_size >= 0 else 0
    try:
        with open(path, "rb", buffering=0) as f:
            f.seek(pos, os.SEEK_SET)
            while time.time() < end:
                chunk = f.read()
                if chunk:
                    text = chunk.decode(errors="ignore")
                    for line in text.splitlines():
                        m = pat.search(line)
                        if m:
                            try:
                                val = int(m.group(1))
                                series.append((val, line.strip()))
                            except Exception:
                                pass
                time.sleep(interval_s)
    except Exception:
        return series
    return series


def measure_mode(base: str, rtsp: str, profile: str, engine_type: str, opts: Dict[str, Any],
                 log_path: Optional[str], duration_sec: int, warmup_sec: int,
                 timeout: float) -> Dict[str, Any]:
    """
    仅通过 CP HTTP 与 VA 交互：
      - POST /api/control/set_engine 切换推理引擎/选项
      - POST /api/subscriptions 创建订阅（CP 通过 gRPC 通知 VA 订阅流）
      - tail VA 日志文件中的 ms.nms boxes 行作为检测框数量的观测指标
      - DELETE /api/subscriptions/{id} 释放订阅

    不再依赖 VA 的 HTTP /api/subscribe 或 /api/pipelines。
    """
    wait_ready(base, timeout, max_wait=3)
    set_engine(base, engine_type, opts, timeout)
    wait_ready(base, timeout, max_wait=3)
    stream_id = f"cmp_{uuid.uuid4().hex[:6]}"
    sub_payload = {"stream_id": stream_id, "profile": profile, "source_uri": rtsp}
    sub_resp = _post(base, "/api/subscriptions", sub_payload, timeout)
    cp_id = ""
    if isinstance(sub_resp, dict):
        data = sub_resp.get("data") or {}
        cp_id = data.get("id", "")
    try:
        # 给 VA 一点时间建立订阅与 pipeline
        time.sleep(max(0, warmup_sec))
        initial_size = os.path.getsize(log_path) if (log_path and os.path.isfile(log_path)) else -1
        # 这里只通过日志观测 boxes，不再依赖 /api/pipelines 的 processed_frames
        series = tail_boxes_series(log_path, initial_size, 0.2, duration_sec) if log_path else []
        boxes = [v for v, _ in series]
        lines = [s for _, s in series]
        return {"frames": len(boxes), "boxes": boxes, "lines": lines}
    finally:
        if cp_id:
            unsubscribe_cp(base, cp_id, timeout)


def summarize_pairs(cpu_boxes: List[int], gpu_boxes: List[int],
                    cpu_lines: List[str], gpu_lines: List[str]) -> None:
    n = min(len(cpu_boxes), len(gpu_boxes))
    print(f"[info] cpu_samples={len(cpu_boxes)} gpu_samples={len(gpu_boxes)} paired={n}")
    if n == 0:
        print("[warn] no overlapping box samples; cannot compare per-frame counts.")
        return

    diffs = [gpu_boxes[i] - cpu_boxes[i] for i in range(n)]
    abs_diffs = [abs(d) for d in diffs]
    max_abs = max(abs_diffs)
    mean_abs = mean(abs_diffs) if abs_diffs else 0.0

    print(f"[summary] cpu_median={median(cpu_boxes) if cpu_boxes else 'n/a'} "
          f"gpu_median={median(gpu_boxes) if gpu_boxes else 'n/a'}")
    print(f"[summary] mean_abs_diff={mean_abs:.3f} max_abs_diff={max_abs}")

    # Print a few worst-case frames with对应日志行，便于排查具体时刻
    worst_indices = sorted(range(n), key=lambda i: abs_diffs[i], reverse=True)[:10]
    print("[details] top per-sample differences (idx, cpu, gpu, diff):")
    for idx in worst_indices:
        cpu_line = cpu_lines[idx] if idx < len(cpu_lines) else ""
        gpu_line = gpu_lines[idx] if idx < len(gpu_lines) else ""
        print(f"  #{idx:04d}: cpu={cpu_boxes[idx]} gpu={gpu_boxes[idx]} diff={diffs[idx]:+d}")
        if cpu_line:
            print(f"    cpu_log: {cpu_line}")
        if gpu_line:
            print(f"    gpu_log: {gpu_line}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8082")
    ap.add_argument("--rtsp", default="rtsp://127.0.0.1:8554/camera_01")
    ap.add_argument("--profile", default="det_720p")
    ap.add_argument("--duration-sec", type=int, default=12)
    ap.add_argument("--warmup-sec", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=6.0)
    args = ap.parse_args()

    base = args.base.rstrip("/")
    log_path = pick_log_file(base, args.timeout)
    print(f"[info] log_path={log_path}")

    if not log_path:
        print("[error] cannot locate video-analyzer log file; ensure VA is running with file logging enabled.")
        return 2

    # CPU-like path: stage device outputs to host + CPU NMS
    cpu = measure_mode(
        base,
        args.rtsp,
        args.profile,
        "ort-cuda",
        {
            "use_io_binding": True,
            "device_output_views": False,
            "stage_device_outputs": True,
            "use_cuda_nms": False,
        },
        log_path,
        args.duration_sec,
        args.warmup_sec,
        args.timeout,
    )
    print(f"[cpu] frames={cpu['frames']} samples={len(cpu['boxes'])}")

    # GPU/Iobinding path: device views + CUDA NMS
    gpu = measure_mode(
        base,
        args.rtsp,
        args.profile,
        "ort-cuda",
        {
            "use_io_binding": True,
            "device_output_views": True,
            "stage_device_outputs": False,
            "use_cuda_nms": True,
        },
        log_path,
        args.duration_sec,
        args.warmup_sec,
        args.timeout,
    )
    print(f"[gpu] frames={gpu['frames']} samples={len(gpu['boxes'])}")

    # Basic sanity: both modes must process some frames
    assert cpu["frames"] > 0 and gpu["frames"] > 0, "no frames processed in one of the modes"

    summarize_pairs(cpu["boxes"], gpu["boxes"], cpu.get("lines", []), gpu.get("lines", []))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
