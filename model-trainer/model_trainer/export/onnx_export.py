from typing import Any, Dict
import os
import torch


def export_onnx(model: torch.nn.Module, export_cfg: Dict[str, Any]) -> str:
    onnx_enable = bool(export_cfg.get('onnx', True))
    if not onnx_enable:
        return ''
    opset = int(export_cfg.get('opset', 17))
    dynamic = bool(export_cfg.get('dynamic_axes', False))
    input_size = export_cfg.get('input_size', [1, 3, 224, 224])
    os.makedirs('artifacts/exports', exist_ok=True)
    out = 'artifacts/exports/model.onnx'
    model.eval()
    dummy = torch.randn(*input_size)
    dyn = None
    if dynamic:
        dyn = {0: 'N'}
        dynamic_axes = {'input': {0: 'N'}, 'output': {0: 'N'}}
    else:
        dynamic_axes = None
    torch.onnx.export(
        model,
        dummy,
        out,
        input_names=['input'],
        output_names=['output'],
        dynamic_axes=dynamic_axes,
        opset_version=opset,
    )
    return out

