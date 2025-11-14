# CONTEXT（2025-11-14，IOBinding & GPU 零拷贝）

本文件汇总当前对话中围绕“VA GPU 零拷贝推理 + Triton 引擎 + YOLO 检测框一致性 + 前端分析面板”的关键结论，作为训练/部署/调参与 M0–M2 路线图的基线上下文。

---

## 一、系统角色与边界（更新版）

- **video-analyzer（VA）**
  - 只对外暴露 gRPC；HTTP（/whep、/api/engine/set 等）在生产构建中可以禁用，由 CP 统一对外。
  - 职责：RTSP 解码（NVDEC）、多阶段图执行（`analyzer_multistage_example`）、Triton In-Process 推理、后处理（YOLO decode + NMS）、CUDA/CPU overlay、WebRTC/WHEP 输出。
  - 模型：通过 Triton + TensorRT plan（FP32/FP16）加载 YOLOv12x 等模型。

- **controlplane（CP）**
  - 唯一 HTTP 入口：`/api/*`、`/whep`。
  - 负责：
    - 训练编排与模型一键部署（Trainer + MLflow + MinIO）。
    - 通过 gRPC 调 VA：SetEngine、SubscribePipeline、ListPipelines 等。
    - 通过 LRO `/api/subscriptions` 暴露订阅生命周期与 phase/timeline。
    - `/whep` 反向代理 VA WHEP 接口，附加 CORS 与 Location 重写。

- **web-front**
  - Vue + Element Plus 单页应用。
  - `Sources` / `Pipelines` 列表：通过 CP 的 `/api/sources`、`/api/pipelines` 探测可用源与 pipeline。
  - `AnalysisPanel` 页面：
    - 通过 CP `/api/subscriptions` 新建订阅，监控 SSE phase/timeline。
    - 通过 `WhepPlayer` 播放 `whep_url` 对应的 H.264 轨。
    - 通过 `/api/control/pipeline_mode` 控制“分析+overlay / raw 直通”。

- **model-trainer 与基础设施**
  - Trainer：FastAPI + PyTorch + MLflow，产出 `model.onnx` + `model.yaml`，上传 MinIO。
  - MySQL：`cv_cp` 库存储源、pipeline、graph、训练/部署记录。
  - MinIO + MLflow：统一存放模型及训练工件。
  - Docker Compose：拉起 mysql/minio/mlflow/trainer/va/cp/web/vsm。

---

## 二、VA 推理与 GPU 零拷贝路径

1. **零拷贝主链路**
   - `source_nvdec_cuda`：使用 NVDEC 解码 RTSP，填充 `core::Frame.device`（NV12，on_gpu=true），不再强制生成 CPU BGR。
   - `LetterboxPreprocessorCUDA`/`NodeRoiBatchCuda`：
     - 对 NV12/BGR 使用双线性插值 + 114 填充 + letterbox，生成 NCHW FP32 tensor。
     - 通过 `ctx.stream` 与 ORT/Triton 的 user_compute_stream 对齐，实现预处理与推理在同一 CUDA stream。
   - `OrtModelSession / TensorRTModelSession`：
     - 通过 engine.options 控制 provider（cuda/tensorrt/triton）、设备号、IoBinding 缓冲大小等。
     - FP16/INT8 由 `trt_fp16`、`trt_int8` 控制；默认 FP32 校准一致性。

2. **IOBinding 与 decode/NMS**
   - IOBinding 输入：统一视为 NCHW FP32 连续内存，避免 stride/pitch 带来的空洞。
   - YOLO GPU decode：
     - `yolo_decode_to_yxyx` / `_fp16` 在 GPU 上完成 `(cx,cy,w,h,score,cls)`→`yxyx` 的转换。
     - 新增配置：
       - `engine.options.yolo_decode_fp16=false`：无论模型输出为 F16/F32，一律在 GPU 上 half→float 后用 FP32 decode。
       - `true`：若输出为 F16 则直接走 FP16 decode。
   - GPU NMS：
     - `nms_yxyx_per_class` 重写为“稳定排序（score/class/坐标/index） + bitmask + 顺序扫描”的确定性实现。
     - IoU 定义、阈值比较（`> iou_thr`）与 CPU `nonMaxSuppression` 对齐，按类别做 NMS。

3. **CPU 路径（基线参考）**
   - CPU 预处理：OpenCV 双线性 letterbox + NCHW FP32。
   - CPU decode + NMS：`YoloDetectionPostprocessor` 在 host 上解码、按类贪心 NMS。
   - CPU 路径被视为“参考真值”，用于对齐 GPU 零拷贝路径的行为。

---

## 三、CPU/GPU 检测框差异与校准

1. **现象**
   - 在相同源、相同 graph（`analyzer_multistage_example`）、相同 NMS `conf/iou` 下：
     - 某些帧 GPU 比 CPU 少 4–6 个框（典型是远处的小人/边缘目标）。
     - 也有帧 GPU 比 CPU 多很多框（例如 `cpu=2,gpu=18`），说明 decode+NMS 行为既可能更“谨慎”也可能更“乐观”。
   - 单纯统一 FP32 精度并不能消除差异，原因在于：
     - Triton/TensorRT 前向本身使用不同算子和 tactic，logits 分布略有差异。
     - NMS 是非线性的，边界上的 tiny 差异会放大成“有/无框”。

2. **诊断脚本**
   - `compare_cpu_gpu_boxes_detail.py`：
     - 通过 CP `/api/control/set_engine` 切换 CPU-like（CPU NMS）和 GPU NMS 两种模式。
     - 通过 CP `/api/subscriptions` 建立订阅，仅依赖 CP HTTP，不需要 VA REST。
     - tail `logs/video-analyzer-release.log` 中 `ms.nms boxes=…`，构造 CPU/GPU boxes 时间序列，并打印 top diff 帧的 CPU/GPU 日志行。
   - `suggest_gpu_nms_thresholds.py`：
     - 从 graph YAML 中解析当前 NMS `conf/iou`。
     - 在固定一段视频（如 120s）上统计：
       - CPU/GPU 总 boxes；
       - 每帧差异（mean_abs_diff）、CPU>0/GPU=0 的比例（miss_ratio）。
     - 基于这些统计，对 GPU NMS 给出启发式建议：
       - GPU 明显少框：conf 降一点、iou 升一点；
       - GPU 明显多框：conf 升一点、iou 降一点；
       - 输出一行可直接写回 `analyzer_multistage_example.yaml` 的 `params`。

3. **当前结论**
   - 在当前 `det_720p` + `analyzer_multistage_example` + `conf=0.50,iou=0.55` 的组合下：
     - GPU 总体 boxes 数略多于 CPU，部分帧存在少数漏检。
     - 启发式脚本在 120s 样本上给出的建议仍是保持 `0.50/0.55`，说明当前阈值已较平衡。
   - 对特定场景（小目标极多、误检成本可接受）仍可通过脚本进一步调低 conf、调高 iou，为 GPU 路径定制一套专用 `conf/iou`。

---

## 四、前端分析面板与 CPU/GPU 切换构想

- 现状：
  - `AnalysisPanel` 通过 `useAnalysisStore` 驱动：
    - 创建订阅（CP `/api/subscriptions`）并等待 phase=ready。
    - 自动将 pipeline 置于 raw 模式，然后通过 `setPipelineMode(..., analysis_enabled=true/false)` 控制 overlay。
  - 当前前端尚未暴露“CPU NMS / GPU 零拷贝 NMS”开关。

- 设计思路（后续工作）：
  - 在 `AnalysisPanel` 工具栏新增一个 Switch，例如：
    - `GPU 零拷贝` on/off，内部映射到 CP `/api/control/set_engine`：
      - off：`use_cuda_preproc=false,use_cuda_nms=false`（CPU 预处理+NMS，推理仍在 GPU/Triton）。
      - on：`use_cuda_preproc=true,use_cuda_nms=true` + engine.options 中的 `yolo_decode_fp16`/`trt_fp16`。
  - 前端在切换时：
    - 先停止当前订阅（cancelSubscription），更新 Engine 配置，再重新启动订阅与分析。
    - 在 UI 上给出明确的“精度优先 / 性能优先”提示。

---

## 五、实践建议与约束

- 对关键 profile（如看小人、看车牌）：
  - 优先在 FP32 + CPU NMS 下校准出“基准行为”，再开启 Triton FP16 和 GPU NMS。
  - 使用 `compare_cpu_gpu_boxes_detail.py` 和 `suggest_gpu_nms_thresholds.py` 对 GPU 路径做一次阈值重标定。

- 精度与性能：
  - 若 GPU 路径在关键场景仍明显弱于 CPU，可考虑：
    - 保留 GPU 预处理 + 推理，但 NMS 统一回到 CPU `nonMaxSuppression`（只 D2H 少量候选框）。
    - 或为该 profile 单独配置更宽松的 `conf/iou`。

- 可观测与调试：
  - 保持 `ms.node_model`、`ms.nms`、`preproc` 相关日志为 debug 级，以便快速定位 decode/NMS 行为。
  - 在 Grafana 中增加：CPU/GPU boxes 数量、GPU decode candidates、miss_ratio 等指标，监控“降准”风险。***
