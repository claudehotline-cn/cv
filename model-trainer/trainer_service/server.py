import os
import time
import threading
from typing import Dict, Any, List

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
            mlflow.log_metrics(metrics)
            job.emit("metrics", metrics)

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
    if os.path.exists(onnx_p): items.append({"name":"model.onnx", "url": url_for('model.onnx')})
    if os.path.exists(man_p):  items.append({"name":"model.yaml", "url": url_for('model.yaml')})
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
