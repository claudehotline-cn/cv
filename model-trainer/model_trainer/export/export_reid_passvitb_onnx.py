import argparse
from pathlib import Path

import torch
from modelscope.models import Model


def export_reid_onnx(
    model_id: str,
    onnx_path: str,
    batch_size: int = 128,
    height: int = 384,
    width: int = 128,
    device: str = "cpu",
    opset: int = 17,
) -> None:
    """
    从 ModelScope 加载 passvitb 行人 ReID 模型，并导出为 ONNX。

    - 输入形状：[batch_size, 3, height, width]
    - 输入名：input
    - 输出名：feat
    - batch 维设置为动态轴（dynamic_axes），方便 Triton 配 max_batch_size>=1
    """
    print(f"[INFO] loading model from ModelScope: {model_id}")
    m = Model.from_pretrained(model_id)
    net = m.model if hasattr(m, "model") else m

    net.eval()
    net.to(device)

    dummy = torch.randn(batch_size, 3, height, width, device=device)

    onnx_path = Path(onnx_path)
    onnx_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] exporting ONNX to {onnx_path} (batch={batch_size})")

    input_names = ["input"]
    output_names = ["feat"]
    dynamic_axes = {
        "input": {0: "batch"},
        "feat": {0: "batch"},
    }

    torch.onnx.export(
        net,
        dummy,
        str(onnx_path),
        input_names=input_names,
        output_names=output_names,
        dynamic_axes=dynamic_axes,
        opset_version=opset,
    )

    print(f"[INFO] export done: {onnx_path.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model-id",
        default="iic/cv_passvitb_image-reid-person_market",
        help="ModelScope 模型 ID",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=128,
        help="导出时使用的 batch 维大小（同时作为 Triton max_batch_size 参考）",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=384,
        help="输入高度，对应 VA 中 ROI.batch 的 out_h",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=128,
        help="输入宽度，对应 VA 中 ROI.batch 的 out_w",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="导出 ONNX 时使用的设备（cpu 或 cuda）",
    )
    parser.add_argument(
        "--opset",
        type=int,
        default=17,
        help="ONNX opset 版本",
    )
    parser.add_argument(
        "--output",
        default="artifacts/exports/reid_passvitb_bs128.onnx",
        help="导出的 ONNX 文件路径",
    )
    args = parser.parse_args()

    export_reid_onnx(
        model_id=args.model_id,
        onnx_path=args.output,
        batch_size=args.batch_size,
        height=args.height,
        width=args.width,
        device=args.device,
        opset=args.opset,
    )


if __name__ == "__main__":
    main()

