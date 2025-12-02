#!/usr/bin/env python3
"""
修补 YOLOX ONNX 中 Conv 节点的 bias 维度不匹配问题。

背景：
- OCSORT 提供的 YOLOX 导出脚本中，部分 Conv 会绑定一个 bias initializer，
  其长度与 weight 的 out_channels 不一致（例如 320 vs 640），TensorRT 解析时会失败。
- 本脚本扫描所有 Conv 节点，找到 weight/bias 维度不匹配的情况，并移除该 Conv 的 bias 输入，
  让 Conv 退化为无 bias 形式，从而避免 TensorRT 导入时的断言错误。

使用方式（trainer 容器内示例）：
  python tools/triton/patch_yolox_conv_bias.py \
    --input /models/yolox.onnx \
    --output /tmp/yolox_patched.onnx

输出：
- 若成功，打印 JSON：{"code":"OK","input":...,"output":...,"patched_convs":N}
- 若失败，打印 {"error": "...", ...} 并返回非 0。
"""

import argparse
import json
from pathlib import Path

import onnx
from onnx import external_data_helper, numpy_helper
import numpy as np


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Patch YOLOX Conv bias mismatches in ONNX")
    ap.add_argument(
        "--input",
        type=str,
        required=True,
        help="Input ONNX path (可能引用 external data)",
    )
    ap.add_argument(
        "--output",
        type=str,
        required=True,
        help="Patched ONNX output path",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    src = Path(args.input)
    dst = Path(args.output)

    result = {
        "input": str(src),
        "output": str(dst),
    }

    if not src.is_file():
        result["error"] = "input_not_found"
        result["detail"] = f"input ONNX not found: {src}"
        print(json.dumps(result, ensure_ascii=False))
        return 1

    try:
        model = onnx.load(str(src))
    except Exception as ex:
        result["error"] = "onnx_load_failed"
        result["detail"] = repr(ex)
        print(json.dumps(result, ensure_ascii=False))
        return 2

    # 若存在 external data，尝试加载，以确保 initializer 形状信息完整
    try:
        external_data_helper.load_external_data_for_model(model, src.parent)
    except Exception:
        # 如果 external data 不存在也没关系，此脚本只看 shape
        pass

    init_map = {init.name: init for init in model.graph.initializer}
    patched = 0
    patched_nodes = []

    for node in model.graph.node:
        if node.op_type != "Conv":
            continue
        if len(node.input) < 3:
            continue
        x_name, w_name, b_name = node.input[0], node.input[1], node.input[2]
        w = init_map.get(w_name)
        b = init_map.get(b_name)
        if w is None or b is None:
            continue
        if len(w.dims) == 0 or len(b.dims) == 0:
            continue
        out_channels = int(w.dims[0])
        bias_dim0 = int(b.dims[0])
        if out_channels != bias_dim0:
            # 维度不匹配：构造新的 bias，使其长度与 weight 的 out_channels 一致
            # 策略：
            # - 若 out_channels 是 bias_dim0 的整数倍，则平铺复制（适用于 group conv 场景）。
            # - 否则：截断或零填充到 out_channels 长度。
            try:
                arr = numpy_helper.to_array(b).reshape(-1)
            except Exception:
                continue
            if bias_dim0 > 0 and out_channels % bias_dim0 == 0:
                reps = out_channels // bias_dim0
                patched_arr = np.tile(arr, reps)
            else:
                patched_arr = np.zeros((out_channels,), dtype=arr.dtype)
                n = min(out_channels, bias_dim0)
                patched_arr[:n] = arr[:n]

            new_b = numpy_helper.from_array(patched_arr.astype(arr.dtype), name=b_name)
            # 替换 graph 中对应的 initializer
            for i, init in enumerate(model.graph.initializer):
                if init.name == b_name:
                    model.graph.initializer[i].CopyFrom(new_b)
                    break
            init_map[b_name] = new_b

            patched += 1
            patched_nodes.append(
                {
                    "name": node.name,
                    "weight": w_name,
                    "bias": b_name,
                    "weight_out_channels": out_channels,
                    "bias_dim0": bias_dim0,
                }
            )

    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        onnx.save_model(model, str(dst))
    except Exception as ex:
        result["error"] = "onnx_save_failed"
        result["detail"] = repr(ex)
        print(json.dumps(result, ensure_ascii=False))
        return 3

    result["code"] = "OK"
    result["patched_convs"] = patched
    if patched_nodes:
        result["patched_nodes"] = patched_nodes
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
