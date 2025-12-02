#!/usr/bin/env python3
"""
基于 ModelScope limengying/ocsort 工程与 ocsort_x 检查点，导出 YOLOX-X 检测模型为 ONNX。

设计目标：
- 在 trainer 容器中运行，默认使用 /root/.cache/modelscope/hub/models/limengying/ocsort 目录。
- 加载 exps/example/mot/yolox_x_mot17_half.py + weights/ocsort_x.pth.tar。
- 以固定输入尺寸（默认 1x3x800x1440）导出单输出 ONNX。
- 以 JSON 形式输出结果，便于脚本链路集成。

注意：
- 当前 PyTorch/ONNX 组合是否会自动拆分 external data（.onnx.data）取决于运行时版本。
  该脚本只负责导出 ONNX 文件本身，不再在此处强制处理 external data。
"""

import argparse
import json
import sys
from pathlib import Path

import torch


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Export YOLOX-X (OCSORT) to ONNX (single file preferred)")
    ap.add_argument(
        "--root",
        type=str,
        default="/root/.cache/modelscope/hub/models/limengying/ocsort/0_oc_track",
        help="Root directory of 0_oc_track from limengying/ocsort",
    )
    ap.add_argument(
        "--exp-file",
        type=str,
        default="exps/example/mot/yolox_x_mot17_half.py",
        help="Relative path to Exp definition file under root",
    )
    ap.add_argument(
        "--checkpoint",
        type=str,
        default="../weights/ocsort_x.pth.tar",
        help="Relative path to ocsort_x checkpoint (from root)",
    )
    ap.add_argument(
        "--output",
        type=str,
        default="/models/yolox.onnx",
        help="Output ONNX path (inside trainer 容器通常为 /models/yolox.onnx)",
    )
    ap.add_argument(
        "--height",
        type=int,
        default=800,
        help="Input image height",
    )
    ap.add_argument(
        "--width",
        type=int,
        default=1440,
        help="Input image width",
    )
    ap.add_argument(
        "--opset",
        type=int,
        default=12,
        help="ONNX opset version",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()

    root = Path(args.root)
    exp_file = root / args.exp_file
    ckpt_path = (root / args.checkpoint).resolve()
    out_path = Path(args.output)

    result = {
        "root": str(root),
        "exp_file": str(exp_file),
        "checkpoint": str(ckpt_path),
        "output": str(out_path),
        "height": int(args.height),
        "width": int(args.width),
        "opset": int(args.opset),
    }

    if not root.is_dir():
        result["error"] = "root_not_found"
        result["detail"] = f"root directory not found: {root}"
        print(json.dumps(result, ensure_ascii=False))
        return 1
    if not exp_file.is_file():
        result["error"] = "exp_not_found"
        result["detail"] = f"exp file not found: {exp_file}"
        print(json.dumps(result, ensure_ascii=False))
        return 2
    if not ckpt_path.is_file():
        result["error"] = "checkpoint_not_found"
        result["detail"] = f"checkpoint not found: {ckpt_path}"
        print(json.dumps(result, ensure_ascii=False))
        return 3

    # 将 0_oc_track 根目录加入 sys.path，按 OCSORT 工程习惯导入 Exp
    sys.path.insert(0, str(root))
    try:
        from exps.example.mot.yolox_x_mot17_half import Exp  # type: ignore
    except Exception as ex:  # pragma: no cover - import error path
        result["error"] = "import_exp_failed"
        result["detail"] = repr(ex)
        print(json.dumps(result, ensure_ascii=False))
        return 4

    try:
        exp = Exp()
    except Exception as ex:
        result["error"] = "exp_init_failed"
        result["detail"] = repr(ex)
        print(json.dumps(result, ensure_ascii=False))
        return 5

    # 加载 checkpoint
    try:
        ckpt = torch.load(str(ckpt_path), map_location="cpu")
        if isinstance(ckpt, dict):
            state = ckpt.get("model") or ckpt.get("state_dict") or ckpt
        else:
            state = ckpt
    except Exception as ex:
        result["error"] = "checkpoint_load_failed"
        result["detail"] = repr(ex)
        print(json.dumps(result, ensure_ascii=False))
        return 6

    # 构建 YOLOX 模型并加载权重
    try:
        model = exp.get_model()
        model.eval()
        missing, unexpected = model.load_state_dict(state, strict=False)
        result["missing_keys"] = list(missing) if isinstance(missing, (list, tuple)) else []
        result["unexpected_keys"] = list(unexpected) if isinstance(unexpected, (list, tuple)) else []
    except Exception as ex:
        result["error"] = "build_model_failed"
        result["detail"] = repr(ex)
        print(json.dumps(result, ensure_ascii=False))
        return 7

    # 导出 ONNX
    dummy = torch.randn(1, 3, int(args.height), int(args.width))
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        torch.onnx.export(
            model,
            dummy,
            str(out_path),
            input_names=["images"],
            output_names=["outputs"],
            opset_version=int(args.opset),
            dynamic_axes={"images": {0: "N"}, "outputs": {0: "N"}},
        )
    except Exception as ex:
        result["error"] = "onnx_export_failed"
        result["detail"] = repr(ex)
        print(json.dumps(result, ensure_ascii=False))
        return 8

    try:
        size_bytes = out_path.stat().st_size
    except Exception:
        size_bytes = 0

    result["code"] = "OK"
    result["onnx_size"] = size_bytes
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

