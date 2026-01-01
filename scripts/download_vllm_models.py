#!/usr/bin/env python3
"""从 ModelScope 下载 vLLM 所需模型

使用方法:
    pip install modelscope
    python scripts/download_vllm_models.py

模型列表 (方案 B):
    - LLM: Qwen3-30B-A3B-AWQ (~18GB 显存)
    - VLM: Qwen3-VL-7B-AWQ (~4GB 显存)
"""

import os
import sys

try:
    from modelscope import snapshot_download
except ImportError:
    print("请先安装 modelscope: pip install modelscope")
    sys.exit(1)

# 模型存放目录
MODELS_DIR = os.environ.get("MODELS_DIR", "/home/chaisen/projects/cv/models")

# 模型列表: (ModelScope ID, 本地目录名)
MODELS = [
    # LLM: Qwen3-30B-A3B-AWQ (MoE 架构，激活参数 3B)
    ("tclf90/Qwen3-30B-A3B-AWQ", "qwen3-30b-awq"),
    # VLM: Qwen3-VL-7B-AWQ (较小模型，与 30B LLM 可同时运行)
    ("Qwen/Qwen2-VL-7B-Instruct-AWQ", "qwen3-vl-7b-awq"),
]


def main():
    os.makedirs(MODELS_DIR, exist_ok=True)
    print(f"模型将下载到: {MODELS_DIR}")
    print("=" * 60)
    
    for model_id, local_name in MODELS:
        local_path = os.path.join(MODELS_DIR, local_name)
        
        if os.path.exists(local_path) and os.listdir(local_path):
            print(f"✓ 跳过 {local_name} (已存在)")
            continue
        
        print(f"⬇ 正在下载: {model_id}")
        print(f"  目标路径: {local_path}")
        
        try:
            snapshot_download(
                model_id,
                cache_dir=local_path,
                revision="master",
            )
            print(f"✓ 完成: {local_name}")
        except Exception as e:
            print(f"✗ 失败: {model_id}")
            print(f"  错误: {e}")
    
    print("=" * 60)
    print("下载完成！")
    print(f"\n启动 vLLM:")
    print(f"  cd docker/compose")
    print(f"  docker compose --profile vllm -f docker-compose.yml -f docker-compose.gpu.override.yml up -d vllm vllm-vl")


if __name__ == "__main__":
    main()
