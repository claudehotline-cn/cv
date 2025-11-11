#!/usr/bin/env python3
import argparse, json, os, sys, subprocess, shlex, time

def run(cmd: str, input_bytes: bytes = None, timeout: int = None) -> (int, bytes, bytes):
    p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE if input_bytes else None,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = p.communicate(input=input_bytes, timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill(); out, err = p.communicate()
    return p.returncode, out, err

def post_convert_upload(cp_base: str, model: str, version: str, onnx_path: str):
    url = f"{cp_base.rstrip('/')}/api/repo/convert_upload?model={model}&version={version}&filename=model.onnx"
    cmd = f"curl -sS -X POST -H 'Content-Type: application/octet-stream' --data-binary @{shlex.quote(onnx_path)} '{url}'"
    rc, out, err = run(cmd)
    if rc != 0:
        raise RuntimeError(f"curl convert_upload failed rc={rc} err={err.decode(errors='ignore')}")
    try:
        j = json.loads(out.decode())
    except Exception as ex:
        raise RuntimeError(f"invalid JSON from convert_upload: {ex}; body={out[:256]!r}")
    if j.get('code') not in ('ACCEPTED','OK'):
        raise RuntimeError(f"convert_upload returned error: {j}")
    data = j.get('data') or {}
    events = data.get('events', '')
    job = data.get('job', '')
    if not events:
        # fallback when server only returns path
        events = f"/api/repo/convert/events?job={job}" if job else ''
    if not events:
        raise RuntimeError(f"missing events path in response: {j}")
    if events.startswith('/'):
        events = cp_base.rstrip('/') + events
    return job, events

def stream_sse(url: str, timeout_sec: int = 600):
    # use curl -NsS to stream SSE lines
    cmd = ["curl","-NsS", url]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    start = time.time()
    event = None
    phase = ''
    try:
        for line in p.stdout:
            line = line.rstrip('\n')
            if line.startswith('event:'):
                event = line.split(':',1)[1].strip()
                continue
            if line.startswith('data:'):
                payload = line.split(':',1)[1].strip()
                if event == 'log':
                    try:
                        d = json.loads(payload)
                        print(d.get('line',''))
                    except Exception:
                        print(payload)
                elif event == 'state':
                    try:
                        d = json.loads(payload)
                        phase = d.get('phase', phase)
                        print(f"[state] phase={phase}")
                    except Exception:
                        print(f"[state] {payload}")
                elif event == 'done':
                    try:
                        d = json.loads(payload)
                        phase = d.get('phase', phase)
                    except Exception:
                        pass
                    print(f"[done] phase={phase}")
                    p.terminate()
                    return phase
            if time.time() - start > timeout_sec:
                p.terminate(); raise TimeoutError("SSE timeout")
    finally:
        try:
            p.terminate()
        except Exception:
            pass
    return phase

def main():
    ap = argparse.ArgumentParser(description='Test convert_upload + SSE progress + plan upload')
    ap.add_argument('--cp', default='http://127.0.0.1:18080', help='ControlPlane base URL')
    ap.add_argument('--model', required=True)
    ap.add_argument('--version', default='1')
    ap.add_argument('--onnx', required=True, help='Path to ONNX file')
    ap.add_argument('--repo', default=os.environ.get('TRITON_REPO',''), help='FS repo path to verify plan file exists (optional)')
    ap.add_argument('--timeout', type=int, default=600)
    args = ap.parse_args()

    if not os.path.isfile(args.onnx):
        print(f"ONNX file not found: {args.onnx}", file=sys.stderr)
        return 2

    print(f"[1/3] POST convert_upload model={args.model} version={args.version}")
    job, events = post_convert_upload(args.cp, args.model, args.version, args.onnx)
    print(f"accepted job={job} events={events}")

    print(f"[2/3] Stream SSE: {events}")
    phase = stream_sse(events, timeout_sec=args.timeout)
    if phase != 'done':
        print(f"convert/upload not completed; last phase={phase}", file=sys.stderr)
        return 3

    if args.repo:
        plan = os.path.join(args.repo, args.model, args.version, 'model.plan')
        print(f"[3/3] Verify plan exists: {plan}")
        if not os.path.isfile(plan):
            print(f"plan not found at {plan}", file=sys.stderr)
            return 4
        print("OK: plan exists")
    else:
        print("[3/3] Skip FS verification (no --repo provided)")
    print("SUCCESS")
    return 0

if __name__ == '__main__':
    sys.exit(main())

