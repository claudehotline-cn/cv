#!/usr/bin/env python3
"""
从单个片段的 CPU / GPU boxes 日志，给出“建议的 GPU conf / iou 组合”。

思路（简化版）：
1. 复用 compare_cpu_gpu_boxes_detail.py 的测量逻辑，在同一条流上连续跑：
   - CPU 模式：use_cuda_nms=false（CPU NMS）
   - GPU 模式：use_cuda_nms=true  （CUDA NMS）
   收集两段 boxes 时间序列。
2. 计算：
   - 总体 GPU / CPU boxes 比例；
   - CPU>0 且 GPU=0 的帧比例（GPU 漏检率近似）；
   - GPU>CPU 很多的帧比例（GPU 过多框）。
3. 根据这些统计，围绕当前 graph 里的 nms.conf/nms.iou 做一个简单的启发式调节：
   - 若 GPU 明显少框（尤其是 CPU>0,GPU=0 多）：建议 conf 稍降、iou 稍升；
   - 若 GPU 明显多框（噪声多）：建议 conf 稍升、iou 稍降；
   - 调节步长默认 0.05，限制在 [0.05,0.95]。
4. 打印推荐值，并给出一行可直接粘进 graph YAML 的 params 行，方便手工更新
   analyzer_multistage_example.yaml 之类的配置。

注意：这是启发式脚本，只基于 boxes 数量统计，无法重建所有 per-box 细节，目的是给出一个
“合理起点”，后续你仍可以微调。
"""
from __future__ import annotations

import argparse
import os
import re
from statistics import median
from typing import Tuple

import compare_cpu_gpu_boxes_detail as cmp


def load_nms_conf_iou(graph_path: str) -> Tuple[float, float]:
    """
    从 graph YAML 中解析第一个 post.yolo.nms 节点的 conf / iou。
    目前假定 params 为内联形式，例如：
      params: { conf: "0.50", iou: "0.55", use_cuda: "1" }
    """
    if not os.path.isfile(graph_path):
        raise FileNotFoundError(graph_path)
    with open(graph_path, "r", encoding="utf-8") as f:
        text = f.read()
    idx = text.find("type: post.yolo.nms")
    if idx < 0:
        raise RuntimeError("无法在 graph 中找到 type: post.yolo.nms 节点")
    # 从该节点附近截一段文本，解析 conf/ioU
    seg = text[idx : idx + 400]
    m_conf = re.search(r'conf:\s*"([0-9.]+)"', seg)
    m_iou = re.search(r'iou:\s*"([0-9.]+)"', seg)
    if not (m_conf and m_iou):
        raise RuntimeError("未能在 post.yolo.nms 节点下解析到 conf / iou")
    return float(m_conf.group(1)), float(m_iou.group(1))


def suggest_thresholds(base_conf: float, base_iou: float, cpu_boxes, gpu_boxes) -> Tuple[float, float]:
    """
    根据 CPU/GPU boxes 时间序列的差异，给出简单的 conf / iou 调整建议。
    """
    n = min(len(cpu_boxes), len(gpu_boxes))
    if n == 0:
        return base_conf, base_iou

    cpu_total = sum(cpu_boxes)
    gpu_total = sum(gpu_boxes)
    if cpu_total == 0:
        # 流里几乎没有检测，阈值调多少意义不大
        return base_conf, base_iou

    ratio = gpu_total / cpu_total
    cpu_med = median(cpu_boxes) if cpu_boxes else 0
    gpu_med = median(gpu_boxes) if gpu_boxes else 0

    miss_frames = sum(1 for i in range(n) if cpu_boxes[i] > 0 and gpu_boxes[i] == 0)
    miss_ratio = miss_frames / n

    # 初始建议值：从当前 graph 配置起步
    conf_new = base_conf
    iou_new = base_iou

    # Heuristic 1: GPU 总 boxes 比例
    if ratio < 0.8:
        # GPU 明显少框：降低 conf，适度提高 IoU（减轻 NMS 压制）
        conf_new = max(0.05, base_conf - 0.05)
        iou_new = min(0.95, base_iou + 0.05)
    elif ratio > 1.2:
        # GPU 明显多框：提高 conf，适度降低 IoU
        conf_new = min(0.95, base_conf + 0.05)
        iou_new = max(0.05, base_iou - 0.05)

    # Heuristic 2: 严重漏检（CPU>0,GPU=0）
    if miss_ratio > 0.3:
        # 再额外放宽一点，偏向召回
        conf_new = max(0.05, conf_new - 0.05)
        iou_new = min(0.95, iou_new + 0.05)

    # Heuristic 3: 中位 boxes 差异
    if cpu_med > 0 and gpu_med < cpu_med * 0.7:
        conf_new = max(0.05, conf_new - 0.05)

    # 限制范围
    conf_new = max(0.05, min(0.95, conf_new))
    iou_new = max(0.05, min(0.95, iou_new))
    return conf_new, iou_new


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8082")
    ap.add_argument("--rtsp", default="rtsp://127.0.0.1:8554/camera_01")
    ap.add_argument("--profile", default="det_720p")
    ap.add_argument("--graph", default="docker/config/va/graphs/analyzer_multistage_example.yaml")
    ap.add_argument("--duration-sec", type=int, default=12)
    ap.add_argument("--warmup-sec", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=6.0)
    args = ap.parse_args()

    base = args.base.rstrip("/")

    # 读取 graph 中 NMS 的当前 conf/iou
    try:
        base_conf, base_iou = load_nms_conf_iou(args.graph)
    except Exception as e:  # noqa: BLE001
        print(f"[error] 解析 graph {args.graph} 中 NMS 阈值失败: {e}")
        return 1

    log_path = cmp.pick_log_file(base, args.timeout)
    print(f"[info] graph={args.graph} base_conf={base_conf:.3f} base_iou={base_iou:.3f}")
    print(f"[info] log_path={log_path}")
    if not log_path:
        print("[error] 无法定位 VA 日志文件；请确认 logging 已启用。")
        return 2

    # CPU-like path
    cpu = cmp.measure_mode(
        base,
        args.rtsp,
        args.profile,
        "ort-cuda",
        {
            "use_io_binding": True,
            "device_output_views": False,
            "stage_device_outputs": True,
            "use_cuda_nms": False,
        },
        log_path,
        args.duration_sec,
        args.warmup_sec,
        args.timeout,
    )
    print(f"[cpu] frames={cpu['frames']} samples={len(cpu['boxes'])}")

    # GPU path
    gpu = cmp.measure_mode(
        base,
        args.rtsp,
        args.profile,
        "ort-cuda",
        {
            "use_io_binding": True,
            "device_output_views": True,
            "stage_device_outputs": False,
            "use_cuda_nms": True,
        },
        log_path,
        args.duration_sec,
        args.warmup_sec,
        args.timeout,
    )
    print(f"[gpu] frames={gpu['frames']} samples={len(gpu['boxes'])}")

    if cpu["frames"] <= 0 or gpu["frames"] <= 0:
        print("[error] CPU 或 GPU 模式未处理任何帧，无法给出可靠建议。")
        return 3

    cpu_boxes = cpu["boxes"]
    gpu_boxes = gpu["boxes"]
    n = min(len(cpu_boxes), len(gpu_boxes))
    if n == 0:
        print("[error] CPU/GPU boxes 时间序列为空，无法比较。")
        return 4

    # 打印现状摘要
    from statistics import mean  # noqa: WPS433

    diffs = [gpu_boxes[i] - cpu_boxes[i] for i in range(n)]
    abs_diffs = [abs(d) for d in diffs]
    cpu_total = sum(cpu_boxes)
    gpu_total = sum(gpu_boxes)
    ratio = gpu_total / cpu_total if cpu_total > 0 else 0.0
    miss_frames = sum(1 for i in range(n) if cpu_boxes[i] > 0 and gpu_boxes[i] == 0)
    miss_ratio = miss_frames / n
    print(f"[summary] cpu_total={cpu_total} gpu_total={gpu_total} ratio={ratio:.3f}")
    print(f"[summary] mean_abs_diff={mean(abs_diffs):.3f} miss_ratio(cpu>0,gpu=0)={miss_ratio:.3f}")

    # 计算建议阈值
    conf_new, iou_new = suggest_thresholds(base_conf, base_iou, cpu_boxes, gpu_boxes)
    print(f"[suggest] 推荐的 GPU NMS 阈值：conf={conf_new:.3f}, iou={iou_new:.3f}")

    # 给出一行可直接粘到 graph YAML 的 params 示例
    print("[suggest] 可在 graph 的 post.yolo.nms 节点下设置类似 params 行，例如：")
    print(f"  params: {{ conf: \"{conf_new:.2f}\", iou: \"{iou_new:.2f}\", use_cuda: \"1\" }}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

