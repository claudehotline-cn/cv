import argparse
import json
import os
import sys
from typing import Any, Dict

import mlflow
import numpy as np
import torch

from . import manifest as mf
from .data.datamodule import build_dataloaders
from .tasks.classification import build_model, train_one_experiment, evaluate
from .export.onnx_export import export_onnx


def load_cfg(path: str) -> Dict[str, Any]:
    import yaml
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def override_from_cli(cfg: Dict[str, Any], kv_list):
    # key.sub=value  set nested
    for it in kv_list:
        if '=' not in it:
            continue
        key, val = it.split('=', 1)
        cur = cfg
        keys = key.split('.')
        for k in keys[:-1]:
            if k not in cur or not isinstance(cur[k], dict):
                cur[k] = {}
            cur = cur[k]
        # try cast
        v: Any = val
        if val.lower() in ('true', 'false'):
            v = (val.lower() == 'true')
        else:
            try:
                if '.' in val:
                    v = float(val)
                else:
                    v = int(val)
            except Exception:
                pass
        cur[keys[-1]] = v
    return cfg


def ensure_tracking_uri():
    if not os.environ.get('MLFLOW_TRACKING_URI'):
        # default to local file store within repo logs
        base = os.path.abspath(os.path.join(os.getcwd(), 'logs', 'mlruns'))
        os.makedirs(base, exist_ok=True)
        os.environ['MLFLOW_TRACKING_URI'] = f'file:{base}'


def jline(obj: Dict[str, Any]):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-c', '--config', required=True, help='YAML 配置文件路径')
    ap.add_argument('overrides', nargs='*', help='以 key=value 覆盖配置，例如 data.train_dir=/data/train')
    args = ap.parse_args()

    cfg = load_cfg(args.config)
    cfg = override_from_cli(cfg, args.overrides)
    ensure_tracking_uri()

    seed = int(cfg.get('run', {}).get('seed', 42))
    torch.manual_seed(seed)
    np.random.seed(seed)

    exp = cfg.get('run', {}).get('experiment', 'cv-default')
    run_name = cfg.get('run', {}).get('run_name', 'run')
    device = cfg.get('run', {}).get('device', 'cpu')

    os.makedirs('artifacts/exports', exist_ok=True)

    with mlflow.start_run(run_name=run_name, experiment_id=None):
        # log params
        mlflow.log_params({
            'task': 'classification',
            'arch': cfg.get('model', {}).get('arch', 'resnet18'),
            'epochs': cfg.get('train', {}).get('epochs', 5),
            'batch_size': cfg.get('train', {}).get('batch_size', 16),
            'lr': cfg.get('train', {}).get('lr', 1e-3),
        })

        # data + model
        train_loader, val_loader, num_classes = build_dataloaders(cfg)
        model = build_model(cfg, num_classes).to(device)

        # train
        best = train_one_experiment(model, train_loader, val_loader, cfg, device)
        metrics = evaluate(model, val_loader, device)
        # log metrics
        mlflow.log_metrics(metrics)
        jline({"type": "metrics", "data": metrics})

        # export onnx
        onnx_path = export_onnx(model, cfg.get('export', {}))
        mlflow.log_artifact(onnx_path, artifact_path="exports")
        jline({"type": "artifact", "path": "exports/model.onnx"})

        # manifest
        manifest_text = mf.build_manifest(cfg, metrics)
        with open('artifacts/model.yaml', 'w', encoding='utf-8') as f:
            f.write(manifest_text)
        mlflow.log_artifact('artifacts/model.yaml')

        # done
        run = mlflow.active_run()
        jline({"type": "done", "run_id": run.info.run_id})


if __name__ == '__main__':
    main()

