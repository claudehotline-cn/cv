from typing import Any, Dict
import yaml


def build_manifest(cfg: Dict[str, Any], metrics: Dict[str, float]) -> str:
    opset = int(cfg.get('export', {}).get('opset', 17))
    dynamic = bool(cfg.get('export', {}).get('dynamic_axes', False))
    input_size = cfg.get('export', {}).get('input_size', [1, 3, 224, 224])
    dtype = 'fp32'
    data = {
        'model': {
            'name': cfg.get('register', {}).get('model_name', 'cv/resnet18'),
            'task': 'classification',
            'framework': 'pytorch',
        },
        'exports': {
            'onnx': {
                'opset': opset,
                'dtype': dtype,
                'dynamic_axes': dynamic,
                'input_format': 'NCHW',
            }
        },
        'io': {
            'inputs': [
                { 'name': 'input', 'shape': input_size, 'normalize': [0.0, 1.0], 'color_space': 'RGB' }
            ],
            'outputs': [
                { 'name': 'output' }
            ]
        },
        'compat': {
            'va_min_version': '1.0.0',
            'ort_ep': ['CUDA', 'TensorRT'],
            'trt_min_version': '8.6'
        },
        'metadata': {
            'dataset': cfg.get('data', {}).get('format', 'random'),
            'trainer_commit': 'unknown',
            'metrics': metrics,
        }
    }
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)

