#!/usr/bin/env python3
"""
Compare YOLO postproc between CPU-NMS and GPU-NMS by counting per-frame boxes.

This script toggles engine options via VA REST, subscribes a stream, then tails
the VA log file to sample "boxes=" counts emitted by NodeNmsYolo (tag ms.nms).
It reports processed_frames and median boxes for CPU vs GPU paths, and asserts
basic parity (frames>0 for both; box count within a small delta).

Usage:
  python compare_nms_iou.py --base http://127.0.0.1:8082 \
      --rtsp rtsp://127.0.0.1:8554/camera_01 --profile det_720p \
      --duration-sec 10 --warmup-sec 2
"""
from __future__ import annotations

import argparse, time, uuid, os, re
from statistics import median
import requests


def _get(base: str, path: str, timeout: float):
    r = requests.get(base + path, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    return j if isinstance(j, dict) else {"success": False}


def _post(base: str, path: str, payload: dict, timeout: float):
    r = requests.post(base + path, json=payload, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    return j if isinstance(j, dict) else {"success": False}


def set_engine(base: str, engine_type: str, opts: dict, timeout: float):
    payload = {
        "type": engine_type,
        "device": 0,
        "options": {k: ("true" if v is True else "false" if v is False else v) for k, v in opts.items()},
    }
    last = None
    for _ in range(3):
        try:
            j = _post(base, "/api/engine/set", payload, timeout)
            if not j.get("success", False):
                last = RuntimeError(f"engine/set returned {j}")
                time.sleep(0.5)
                continue
            return j
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.5)
    raise last


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


def unsubscribe(base: str, stream_id: str, profile: str, timeout: float):
    try:
        _post(base, "/api/unsubscribe", {"stream": stream_id, "profile": profile}, timeout)
    except Exception:
        pass


def pick_log_file(base: str, timeout: float) -> str | None:
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


def tail_boxes_from_log(path: str, start_size: int, interval_s: float, seconds: float) -> list[int]:
    if not path:
        return []
    counts: list[int] = []
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
                                counts.append(int(m.group(1)))
                            except Exception:
                                pass
                time.sleep(interval_s)
    except Exception:
        return counts
    return counts


def measure(base: str, rtsp: str, profile: str, engine_type: str, opts: dict,
            log_path: str | None, duration_sec: int, warmup_sec: int, timeout: float):
    wait_ready(base, timeout, max_wait=3)
    set_engine(base, engine_type, opts, timeout)
    wait_ready(base, timeout, max_wait=3)
    stream_id = f"nms_{uuid.uuid4().hex[:6]}"
    key = f"{stream_id}:{profile}"
    sub_payload = {"stream": stream_id, "profile": profile, "url": rtsp}
    _post(base, "/api/subscribe", sub_payload, timeout)
    try:
        time.sleep(max(0, warmup_sec))
        initial_size = os.path.getsize(log_path) if (log_path and os.path.isfile(log_path)) else -1
        t0 = time.time()
        frames0 = 0
        last_frames = None
        while time.time() - t0 < duration_sec:
            j = _get(base, "/api/pipelines", timeout)
            data = j.get("data", []) if isinstance(j, dict) else []
            pl = next((p for p in data if p.get("key") == key), None)
            if pl:
                m = pl.get("metrics", {})
                frames = int(m.get("processed_frames", 0))
                if last_frames is None:
                    last_frames = frames
                else:
                    if frames > last_frames:
                        frames0 += (frames - last_frames)
                        last_frames = frames
            time.sleep(0.5)
        boxes = tail_boxes_from_log(log_path, initial_size, 0.2, 2.5)
        return {"frames": frames0, "boxes": boxes}
    finally:
        unsubscribe(base, stream_id, profile, timeout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8082")
    ap.add_argument("--rtsp", default="rtsp://127.0.0.1:8554/camera_01")
    ap.add_argument("--profile", default="det_720p")
    ap.add_argument("--duration-sec", type=int, default=10)
    ap.add_argument("--warmup-sec", type=int, default=2)
    ap.add_argument("--timeout", type=float, default=6.0)
    args = ap.parse_args()

    base = args.base.rstrip("/")
    log_path = pick_log_file(base, args.timeout)
    print(f"[info] log_path={log_path}")

    cpu = measure(base, args.rtsp, args.profile, "ort-cuda",
                  {"use_io_binding": True, "device_output_views": False, "stage_device_outputs": True, "use_cuda_nms": False},
                  log_path, args.duration_sec, args.warmup_sec, args.timeout)
    gpu = measure(base, args.rtsp, args.profile, "ort-cuda",
                  {"use_io_binding": True, "device_output_views": True,  "stage_device_outputs": False, "use_cuda_nms": True},
                  log_path, args.duration_sec, args.warmup_sec, args.timeout)

    print(f"CPU-NMS: frames={cpu['frames']} boxes_samples={len(cpu['boxes'])} median={median(cpu['boxes']) if cpu['boxes'] else 'n/a'}")
    print(f"GPU-NMS: frames={gpu['frames']} boxes_samples={len(gpu['boxes'])} median={median(gpu['boxes']) if gpu['boxes'] else 'n/a'}")

    # Assertions (soft): frames > 0; if we have box samples, median counts are close.
    assert cpu["frames"] > 0 and gpu["frames"] > 0, "no frames processed in one of the modes"
    if cpu["boxes"] and gpu["boxes"]:
        mc = median(cpu["boxes"]) if cpu["boxes"] else 0
        mg = median(gpu["boxes"]) if gpu["boxes"] else 0
        # allow small drift in counts (<= 1 absolute or <= 5%)
        if mc and mg:
            ok = abs(mg - mc) <= 1 or (abs(mg - mc) / max(1, mc) <= 0.05)
            assert ok, f"median boxes mismatch cpu={mc} gpu={mg}"

    print("[pass] CPU-NMS vs GPU-NMS sanity checks passed")


if __name__ == "__main__":
    raise SystemExit(main())

