"""
Compare pipeline FPS/frames across CPU/GPU and CUDA toggles.

Usage:
  python compare_modes.py --base http://127.0.0.1:8082 \
      --rtsp rtsp://127.0.0.1:8554/camera_01 --profile det_720p \
      --duration-sec 12 --warmup-sec 2
"""
from __future__ import annotations
import argparse, time, uuid, sys
import requests
import time as _time


def get_json(base: str, path: str, timeout: int):
    r = requests.get(base + path, timeout=timeout)
    r.raise_for_status()
    return r.json()


def post_json(base: str, path: str, payload: dict, timeout: int):
    r = requests.post(base + path, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def unsubscribe(base: str, stream_id: str, profile: str, timeout: int):
    try:
        post_json(base, "/api/unsubscribe", {"stream_id":stream_id, "profile":profile}, timeout)
    except Exception:
        pass


def _wait_ready(base: str, timeout: int, max_wait: int = 6):
    deadline = _time.time() + max_wait
    while _time.time() < deadline:
        try:
            r = requests.get(base + "/api/system/info", timeout=timeout)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        _time.sleep(0.5)
    return False


def set_engine(base: str, engine_type: str, opts: dict, timeout: int):
    payload = {
        "type": engine_type,
        "device": 0,
        "options": {k: ("true" if v else "false") if isinstance(v, bool) else v for k,v in opts.items()}
    }
    # Try with small retry window to mitigate transient restarts
    last = None
    for _ in range(3):
        try:
            return post_json(base, "/api/engine/set", payload, timeout)
        except Exception as e:
            last = e
            _time.sleep(0.5)
            _wait_ready(base, timeout, max_wait=2)
    raise last


def measure_mode(base: str, rtsp: str, profile: str, engine_type: str, opts: dict, duration: int, warmup: int, timeout: int):
    # ensure backend is reachable before switching engine
    _wait_ready(base, timeout, max_wait=3)
    set_engine(base, engine_type, opts, timeout)
    _wait_ready(base, timeout, max_wait=3)
    stream_id = f"cmp_{uuid.uuid4().hex[:6]}"
    key = f"{stream_id}:{profile}"
    post_json(base, "/api/subscribe", {"stream_id":stream_id, "profile":profile, "url":rtsp}, timeout)
    try:
        time.sleep(warmup)
        start = time.time()
        last_frames = None
        fps_samples = []
        frames_gained = 0
        while time.time() - start < duration:
            data = get_json(base, "/api/pipelines", timeout).get("data", [])
            pl = next((p for p in data if p.get("key")==key), None)
            if pl:
                m = pl.get("metrics", {})
                fps = float(m.get("fps", 0.0))
                frames = int(m.get("processed_frames", 0))
                fps_samples.append(fps)
                if last_frames is None:
                    last_frames = frames
                elif frames > last_frames:
                    frames_gained += (frames - last_frames)
                    last_frames = frames
            time.sleep(1)
        avg_fps = sum(fps_samples)/len(fps_samples) if fps_samples else 0.0
        return {"avg_fps": avg_fps, "frames": frames_gained}
    finally:
        unsubscribe(base, stream_id, profile, timeout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8082")
    ap.add_argument("--rtsp", required=True)
    ap.add_argument("--profile", default="det_720p")
    ap.add_argument("--duration-sec", type=int, default=12)
    ap.add_argument("--warmup-sec", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=10)
    args = ap.parse_args()

    modes = [
        ("cpu", "ort-cpu", {"use_io_binding": False}),
        ("gpu_cpu_nms_overlay", "ort-cuda", {"use_io_binding": True, "device_output_views": False, "use_cuda_nms": False, "render_cuda": False}),
        ("gpu_cuda_nms", "ort-cuda", {"use_io_binding": True, "device_output_views": True, "use_cuda_nms": True, "render_cuda": False}),
        ("gpu_cuda_overlay", "ort-cuda", {"use_io_binding": True, "device_output_views": True, "use_cuda_nms": False, "render_cuda": True}),
        ("gpu_cuda_nms_overlay", "ort-cuda", {"use_io_binding": True, "device_output_views": True, "use_cuda_nms": True, "render_cuda": True}),
    ]

    results = []
    for name, etype, opts in modes:
        try:
            r = measure_mode(args.base, args.rtsp, args.profile, etype, opts, args.duration_sec, args.warmup_sec, args.timeout)
            results.append((name, r["avg_fps"], r["frames"]))
            print(f"mode={name} avg_fps={r['avg_fps']:.2f} frames={r['frames']}")
        except Exception as e:
            print(f"mode={name} ERROR: {e}")

    print("\nSummary:")
    for name, fps, frames in results:
        print(f"- {name:22} fps={fps:6.2f} frames={frames}")

if __name__ == "__main__":
    sys.exit(main())
