#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

import torch


def parse_input_size(text: str):
    parts = text.replace("x", ",").split(",")
    dims = [int(p.strip()) for p in parts if p.strip()]
    if not dims:
        raise ValueError("invalid input_size")
    return dims


def load_model(ckpt: Path) -> torch.nn.Module:
    try:
        m = torch.jit.load(str(ckpt), map_location="cpu")
        return m
    except Exception:
        obj = torch.load(str(ckpt), map_location="cpu")
        if isinstance(obj, torch.nn.Module):
            return obj
        if isinstance(obj, dict):
            inner = obj.get("model") or obj.get("net") or obj.get("module")
            if isinstance(inner, torch.nn.Module):
                return inner
    raise RuntimeError("unsupported checkpoint format for %s" % ckpt)


def main():
    ap = argparse.ArgumentParser(description="Export ocsort_x PyTorch checkpoint to ONNX")
    ap.add_argument(
        "--checkpoint",
        type=str,
        default="/home/chaisen/projects/cv/docker/model/ocsort_x.pth.tar",
        help="Path to ocsort_x PyTorch checkpoint",
    )
    ap.add_argument(
        "--output",
        type=str,
        default="/home/chaisen/projects/cv/docker/model/ocsort_x.onnx",
        help="Output ONNX path",
    )
    ap.add_argument(
        "--input-size",
        type=str,
        default="1,3,640,640",
        help="Dummy input size, e.g. 1,3,640,640 or 1x3x640x640",
    )
    ap.add_argument(
        "--opset",
        type=int,
        default=17,
        help="ONNX opset version",
    )
    ap.add_argument(
        "--dynamic-batch",
        action="store_true",
        help="Enable dynamic batch axis for ONNX",
    )
    args = ap.parse_args()

    ckpt_path = Path(args.checkpoint)
    if not ckpt_path.is_file():
        print(json.dumps({"error": "missing_checkpoint", "path": str(ckpt_path)}))
        return 1

    try:
        input_size = parse_input_size(args.input_size)
    except Exception as ex:
        print(json.dumps({"error": "invalid_input_size", "detail": str(ex)}))
        return 2

    try:
        model = load_model(ckpt_path)
    except Exception as ex:
        print(json.dumps({"error": "load_failed", "detail": str(ex)}))
        return 3

    model.eval()
    dummy = torch.randn(*input_size)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.dynamic_batch:
        dynamic_axes = {"input": {0: "N"}, "output": {0: "N"}}
    else:
        dynamic_axes = None

    try:
        torch.onnx.export(
            model,
            dummy,
            str(out_path),
            input_names=["input"],
            output_names=["output"],
            dynamic_axes=dynamic_axes,
            opset_version=int(args.opset),
        )
    except Exception as ex:
        print(json.dumps({"error": "export_failed", "detail": str(ex)}))
        return 4

    print(
        json.dumps(
            {
                "checkpoint": str(ckpt_path),
                "onnx": str(out_path),
                "input_size": input_size,
                "opset": int(args.opset),
                "dynamic_batch": bool(args.dynamic_batch),
                "code": "OK",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

