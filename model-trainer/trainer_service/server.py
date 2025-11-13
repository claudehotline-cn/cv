import os
import time
import threading
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from model_trainer.data.datamodule import build_dataloaders
from model_trainer.tasks.classification import build_model, train_one_experiment, evaluate
from model_trainer.export.onnx_export import export_onnx
from model_trainer.manifest import build_manifest

import mlflow
import torch
import numpy as np
import json
import os
import math

try:
    import boto3
    from botocore.config import Config as BotoConfig
except Exception:
    boto3 = None


class Event:
    def __init__(self, kind: str, data: Dict[str, Any]):
        self.kind = kind
        self.data = data


class Job:
    def __init__(self, job_id: str, cfg: Dict[str, Any]):
        self.id = job_id
        self.cfg = cfg
        self.status = "created"
        self.phase = "created"
        self.progress = 0.0
        self.events: List[Event] = []
        self.done = False
        self.err: str = ""
        self.lock = threading.Lock()
        self.last_metrics: Dict[str, float] = {}

    def emit(self, kind: str, data: Dict[str, Any]):
        with self.lock:
            self.events.append(Event(kind, data))


class JobManager:
    def __init__(self):
        self.mu = threading.Lock()
        self.jobs: Dict[str, Job] = {}

    def create(self, cfg: Dict[str, Any]) -> Job:
        job_id = f"t_{int(time.time()*1e6):x}"
        j = Job(job_id, cfg)
        with self.mu:
            self.jobs[job_id] = j
        return j

    def get(self, job_id: str) -> Job:
        with self.mu:
            return self.jobs.get(job_id)


jobs = JobManager()
app = FastAPI(title="cv-trainer-service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


def ensure_tracking_uri():
    if not os.environ.get('MLFLOW_TRACKING_URI'):
        base = os.path.abspath(os.path.join(os.getcwd(), 'logs', 'mlruns'))
        os.makedirs(base, exist_ok=True)
        os.environ['MLFLOW_TRACKING_URI'] = f'file:{base}'


def maybe_s3_client():
    # Guard: require boto3 and TRAINER_S3_BUCKET and AWS_ENDPOINT_URL
    bucket = os.environ.get('TRAINER_S3_BUCKET')
    endpoint = os.environ.get('AWS_ENDPOINT_URL') or os.environ.get('AWS_S3_ENDPOINT')
    if not (boto3 and bucket and endpoint):
        return None
    session = boto3.session.Session(
        aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
        region_name=os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION') or 'us-east-1',
    )
    cfg = BotoConfig(signature_version='s3v4', s3={'addressing_style': os.environ.get('S3_ADDRESSING_STYLE', 'path')})
    s3 = session.client('s3', endpoint_url=endpoint, use_ssl=endpoint.startswith('https'), verify=False, config=cfg)
    return { 'client': s3, 'bucket': bucket, 'prefix': os.environ.get('TRAINER_S3_PREFIX','trainer') }

def s3_put(cli, bucket: str, key: str, local_path: str) -> str:
    assert os.path.exists(local_path), f'file not found: {local_path}'
    cli.upload_file(local_path, bucket, key)
    return f's3://{bucket}/{key}'


def run_training(job: Job):
    try:
        ensure_tracking_uri()
        cfg = job.cfg
        seed = int(cfg.get('run', {}).get('seed', 42))
        torch.manual_seed(seed)
        np.random.seed(seed)
        device = cfg.get('run', {}).get('device', 'cpu')
        job.status = "running"; job.phase = "preparing"; job.progress = 0.0
        job.emit("state", {"phase": job.phase, "progress": job.progress})

        with mlflow.start_run(run_name=cfg.get('run', {}).get('run_name', 'run')) as run:
            # Prepare per-job artifact dir
            job_dir = os.path.join('artifacts', job.id)
            exp_dir = os.path.join(job_dir, 'exports')
            os.makedirs(exp_dir, exist_ok=True)
            train_loader, val_loader, num_classes = build_dataloaders(cfg)
            model = build_model(cfg, num_classes).to(device)
            job.phase = "running"; job.progress = 0.05
            job.emit("state", {"phase": job.phase, "progress": job.progress})

            train_one_experiment(model, train_loader, val_loader, cfg, device)
            metrics = evaluate(model, val_loader, device)
            job.last_metrics = { k: float(v) for k,v in (metrics or {}).items() }
            mlflow.log_metrics(job.last_metrics)
            job.emit("metrics", job.last_metrics)

            onnx_path = export_onnx(model, cfg.get('export', {}))
            if onnx_path:
                # move to per-job dir
                try:
                    dst = os.path.join(exp_dir, 'model.onnx')
                    os.replace(onnx_path, dst)
                    onnx_path = dst
                except Exception:
                    pass
                mlflow.log_artifact(onnx_path, artifact_path="exports")
                job.phase = "exporting"; job.progress = 0.9
                job.emit("artifact", {"path": "exports/model.onnx"})
                job.emit("state", {"phase": job.phase, "progress": job.progress})

            manifest_text = build_manifest(cfg, metrics)
            with open(os.path.join(job_dir, 'model.yaml'), 'w', encoding='utf-8') as f:
                f.write(manifest_text)
            mlflow.log_artifact(os.path.join(job_dir, 'model.yaml'))

            # Optional: upload to S3/MinIO if configured
            try:
                s3c = maybe_s3_client()
                if s3c:
                    cli = s3c['client']; bucket = s3c['bucket']; prefix = s3c['prefix']
                    base_key = f"{prefix}/{job.id}/"
                    if os.path.exists(onnx_path):
                        uri = s3_put(cli, bucket, base_key + 'exports/model.onnx', onnx_path)
                        job.emit('artifact', { 's3_uri': uri })
                    man_local = os.path.join(job_dir, 'model.yaml')
                    if os.path.exists(man_local):
                        uri = s3_put(cli, bucket, base_key + 'model.yaml', man_local)
                        job.emit('artifact', { 's3_uri': uri })
            except Exception as ex:
                job.emit('error', { 'msg': f's3_upload_failed: {ex!s}' })

            job.status = "done"; job.phase = "done"; job.progress = 1.0; job.done = True
            job.emit("done", {"run_id": run.info.run_id})
    except Exception as ex:
        job.status = "failed"; job.phase = "failed"; job.done = True; job.err = str(ex)
        job.emit("error", {"msg": job.err})


@app.post("/api/train/start")
async def api_start(req: Request):
    cfg = await req.json()
    j = jobs.create(cfg)
    th = threading.Thread(target=run_training, args=(j,), daemon=True)
    th.start()
    return JSONResponse({"code": "ACCEPTED", "data": {"job": j.id, "events": f"/api/train/events?id={j.id}"}}, status_code=202)


@app.get("/api/train/status")
async def api_status(id: str):
    j = jobs.get(id)
    if not j:
        return JSONResponse({"code": "NOT_FOUND"}, status_code=404)
    d = {"id": j.id, "status": j.status, "phase": j.phase, "progress": j.progress}
    if j.last_metrics:
        d["metrics_summary"] = j.last_metrics
    if j.err:
        d["error"] = j.err
    return {"code": "OK", "data": d}


@app.get("/api/train/list")
async def api_list():
    out = []
    with jobs.mu:
        for j in jobs.jobs.values():
            out.append({
                "id": j.id,
                "status": j.status,
                "phase": j.phase,
                "progress": j.progress
            })
    return {"code": "OK", "data": out}

@app.get("/api/train/artifacts")
async def api_artifacts(id: str, request: Request):
    j = jobs.get(id)
    if not j:
        return JSONResponse({"code":"NOT_FOUND"}, status_code=404)
    job_dir = os.path.join('artifacts', j.id)
    items = []
    onnx_p = os.path.join(job_dir, 'exports', 'model.onnx')
    man_p  = os.path.join(job_dir, 'model.yaml')
    def url_for(name: str):
        return str(request.url_for('download_artifact')) + f"?id={j.id}&name={name}"
    # Try to list S3 URIs from emitted events
    s3_uris = []
    with j.lock:
        for ev in j.events:
            if ev.kind == 'artifact' and isinstance(ev.data, dict) and 's3_uri' in ev.data:
                s3_uris.append(ev.data['s3_uri'])
    def size_mb(p: str) -> Optional[float]:
        try:
            b = os.path.getsize(p); return round(b / (1024.0*1024.0), 3)
        except Exception:
            return None
    if os.path.exists(onnx_p):
        item = {"name":"model.onnx", "url": url_for('model.onnx')}
        sm = size_mb(onnx_p)
        if sm is not None: item["size_mb"] = sm
        for u in s3_uris:
            if u.endswith('/exports/model.onnx') or u.endswith('model.onnx'):
                item["s3_uri"] = u
        items.append(item)
    if os.path.exists(man_p):
        item = {"name":"model.yaml", "url": url_for('model.yaml')}
        sm = size_mb(man_p)
        if sm is not None: item["size_mb"] = sm
        for u in s3_uris:
            if u.endswith('/model.yaml') or u.endswith('model.yaml'):
                item["s3_uri"] = u
        items.append(item)
    return {"code":"OK","data":items}

@app.get("/api/train/artifacts/download", name="download_artifact")
async def api_artifact_download(id: str, name: str):
    j = jobs.get(id)
    if not j:
        return Response(content="", status_code=404)
    job_dir = os.path.join('artifacts', j.id)
    if name == 'model.onnx':
        path = os.path.join(job_dir, 'exports', 'model.onnx')
        ctype = 'application/octet-stream'
    elif name == 'model.yaml':
        path = os.path.join(job_dir, 'model.yaml')
        ctype = 'text/yaml'
    else:
        return Response(content="", status_code=404)
    if not os.path.exists(path):
        return Response(content="", status_code=404)
    def genf():
        with open(path, 'rb') as f:
            while True:
                chunk = f.read(8192)
                if not chunk: break
                yield chunk
    headers = { 'Content-Disposition': f'attachment; filename="{name}"' }
    return StreamingResponse(genf(), media_type=ctype, headers=headers)

@app.get("/api/train/events")
async def api_events(id: str):
    j = jobs.get(id)
    if not j:
        return Response(content="", status_code=404)

    def gen():
        idx = 0
        while True:
            with j.lock:
                while idx < len(j.events):
                    ev = j.events[idx]
                    idx += 1
                    data = json.dumps(ev.data, ensure_ascii=False)
                    yield f"event: {ev.kind}\n".encode('utf-8')
                    yield f"data: {data}\n\n".encode('utf-8')
                done = j.done
            # keepalive
            yield b": keepalive\n\n"
            if done:
                break
            time.sleep(0.2)

    return StreamingResponse(gen(), media_type='text/event-stream')
