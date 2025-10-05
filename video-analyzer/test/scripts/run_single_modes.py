"""
Run single-mode tests one by one (no in-process mode switching).

Usage:
  python run_single_modes.py --base http://127.0.0.1:8082 \
      --url rtsp://127.0.0.1:8554/camera_01 --profile det_720p \
      --modes cpu gpu_iobind gpu_no_iobind --duration-sec 12 --warmup-sec 3

Outputs a summary and exit 0 if at least one mode passes; 2 otherwise.
"""
from __future__ import annotations
import argparse, time, sys, json
import subprocess
import requests


def get_json(base: str, path: str, timeout: int):
    r = requests.get(base + path, timeout=timeout)
    r.raise_for_status()
    return r.json()


def post_json(base: str, path: str, payload: dict, timeout: int):
    r = requests.post(base + path, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def wait_ready(base: str, timeout: int, max_wait: int = 8) -> bool:
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            r = requests.get(base + "/api/system/info", timeout=timeout)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def set_engine(base: str, engine: str, opts: dict, timeout: int) -> None:
    payload = {
        "type": engine,
        "device": 0,
        "options": {k: ("true" if v is True else "false" if v is False else v) for k, v in opts.items()},
    }
    last = None
    for _ in range(5):
        try:
            post_json(base, "/api/engine/set", payload, timeout)
            return
        except Exception as e:
            last = e
            time.sleep(1.0)
            wait_ready(base, timeout, max_wait=4)
    raise last


def unsubscribe(base: str, stream_id: str, profile: str, timeout: int):
    try:
        post_json(base, "/api/unsubscribe", {"stream_id": stream_id, "profile": profile}, timeout)
    except Exception:
        pass


def run_mode(base: str, url: str, profile: str, engine: str, opts: dict, duration: int, warmup: int, timeout: int):
    name = opts.get("_mode_name", engine)
    print(f"===== Single Mode: {name} =====")
    # readiness and engine
    if not wait_ready(base, timeout, max_wait=8):
        print("[ERR] backend not ready")
        return {"mode": name, "pass": False, "reason": "not_ready"}
    try:
        set_engine(base, engine, {k: v for k, v in opts.items() if not k.startswith("_")}, timeout)
    except Exception as e:
        return {"mode": name, "pass": False, "reason": f"set_engine: {e}"}
    if not wait_ready(base, timeout, max_wait=8):
        return {"mode": name, "pass": False, "reason": "not_ready_after_set"}

    stream_id = f"sm_{int(time.time())%100000}"
    sub_payload = {"stream_id": stream_id, "profile": profile, "url": url}
    ok_sub = False
    last = None
    for _ in range(6):
        try:
            post_json(base, "/api/subscribe", sub_payload, timeout)
            ok_sub = True
            break
        except Exception as e:
            last = e
            time.sleep(1.0)
            wait_ready(base, timeout, max_wait=4)
    if not ok_sub:
        return {"mode": name, "pass": False, "reason": f"subscribe: {last}"}

    key = f"{stream_id}:{profile}"
    try:
        time.sleep(warmup)
        start = time.time()
        last_frames = None
        frames_gained = 0
        fps_samples = []
        while time.time() - start < duration:
            try:
                data = get_json(base, "/api/pipelines", timeout).get("data", [])
                pl = next((p for p in data if p.get("key") == key), None)
                if pl:
                    m = pl.get("metrics", {})
                    frames = int(m.get("processed_frames", 0))
                    fps = float(m.get("fps", 0.0))
                    fps_samples.append(fps)
                    if last_frames is None:
                        last_frames = frames
                    elif frames > last_frames:
                        frames_gained += (frames - last_frames)
                        last_frames = frames
            except Exception:
                pass
            time.sleep(1)
        avg_fps = sum(fps_samples)/len(fps_samples) if fps_samples else 0.0
        passed = frames_gained > 0
        return {"mode": name, "pass": passed, "frames": frames_gained, "avg_fps": avg_fps}
    finally:
        unsubscribe(base, stream_id, profile, timeout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8082")
    ap.add_argument("--url", required=True)
    ap.add_argument("--profile", default="det_720p")
    ap.add_argument("--modes", nargs="*", default=["cpu", "gpu_iobind", "gpu_no_iobind"])
    ap.add_argument("--duration-sec", type=int, default=12)
    ap.add_argument("--warmup-sec", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=10)
    args = ap.parse_args()

    mode_defs = {
        "cpu": ("ort-cpu", {"use_io_binding": False, "_mode_name": "cpu"}),
        "gpu_iobind": ("ort-cuda", {"use_io_binding": True, "device_output_views": True, "_mode_name": "gpu_iobind"}),
        "gpu_no_iobind": ("ort-cuda", {"use_io_binding": False, "_mode_name": "gpu_no_iobind"}),
    }

    results = []
    for m in args.modes:
        if m not in mode_defs:
            print(f"[WARN] unknown mode {m}, skip")
            continue
        engine, opts = mode_defs[m]
        res = run_mode(args.base, args.url, args.profile, engine, opts, args.duration_sec, args.warmup_sec, args.timeout)
        results.append(res)
        print(res)

    ok = any(r.get("pass") for r in results)
    print("\nSummary:")
    for r in results:
        print(json.dumps(r, ensure_ascii=False))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())

