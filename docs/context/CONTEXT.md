# CONTEXT（2025-11-19，Triton + ReID 动态 Batch + OCSORT GPU 内核对齐）

本文件汇总当前围绕 **VA In-Process Triton 集成、ReID 动态 Batch、OCSORT 多阶段 GPU 追踪与日志/内存行为** 的关键结论，作为后续开发与调试的统一上下文。

---

## 一、整体链路与运行环境

- **GPU 与编译目标**
  - 实际 GPU：RTX 5090D，运行时支持较新架构。
  - VA GPU 镜像当前编译参数：`-DCMAKE_CUDA_ARCHITECTURES="120"`，NVCC 目标为 `compute_120,sm_120`。
  - 由于目标架构为 sm_120，`track_ocsort_kernels.cu` 中的 CUDA 核必须严格控制 per‑thread 本地内存使用（否则易触发 `cudaErrorInvalidValue`）。

- **Graph：`analyzer_multistage_ocsort` 汇总**
  - pre → det（Triton YOLOv12x）→ nms → roi.batch.cuda → reid（Triton ReID）→ track.ocsort（OCSORT）→ overlay.cuda。
  - 检测模型：`yolov12x`（Triton In-Process），输入 `images`，输出 `output0`，GPU I/O。
  - ReID 模型：`reid_passvitb`（Triton In-Process），输入 `input`，[N,3,384,128]，输出 `feat`，[N,1536]，GPU 输出。

---

## 二、In-Process Triton 与 ReID 动态 Batch（GPU I/O）

- **TritonInprocModelSession 行为**
  - 代码：`video-analyzer/src/analyzer/triton_inproc_session.cpp/.hpp`。
  - 支持 `use_gpu_input` 与 `use_gpu_output`：
    - `use_gpu_input=true` 时，`AppendInputData` 使用 `TRITONSERVER_MEMORY_GPU` + device_id；
    - 通过 `cudaPointerGetAttributes` 校验输入指针所属 device，并在必要时 `cudaSetDevice`。
  - ReID 路径：
    - `roi.batch.cuda` 生成 `[N,3,384,128]` 的 GPU tensor `tensor:roi_batch`；
    - ReID 节点 `NodeModel` 以 `in="tensor:roi_batch"` 调用 `session_->run`；
    - Triton In-Process 使用 `triton_input: "input"`、`triton_outputs: "feat"`、`triton_gpu_output: "1"`，由 ResponseAllocator 将特征输出直接写入 GPU buffer，形成 `tensor:reid: [N,1536](gpu)`。

- **错误排查与现状**
  - 早期 ReID 路径出现 `input: failed to perform CUDA copy: invalid argument`：
    - 原因：Triton 内部对 GPU 输入执行 CUDA 拷贝时，认为指针/大小/设备不合法。
    - 通过日志增强与 config 检查，确认 MinIO 中 `reid_passvitb/config.pbtxt` 与 plan 一致后，该错误已在当前环境下消失。
  - 当前状态：
    - ReID 节点输出 log 形如 `out0..2=Nx1536(gpu)`，`feat_dim=1536` 成功进入 OCSORT GPU 核心；
    - Triton In-Process 对 YOLO 与 ReID 的 GPU 输入/输出行为稳定。

---

## 三、OCSORT GPU 内核与多阶段匹配对齐

- **核心文件：**
  - `video-analyzer/src/analyzer/cuda/track_ocsort_kernels.hpp/.cu`（GPU 内核接口与实现）。
  - `video-analyzer/src/analyzer/multistage/node_track_ocsort.hpp/.cpp`（多阶段 OC-SORT 节点）。

- **OcsortGpuState**
  - 设备侧持久化结构：
    - 轨迹几何：`d_track_boxes[T,4]`；
    - 轨迹特征：`d_track_feats[T,D]`、`d_track_has_feat[T]`；
    - 生命周期：`d_track_ids[T]`、`d_track_missed[T]`、`d_track_age[T]`、`d_track_hit_streak[T]`；
    - 运动与 Kalman 状态：`d_track_vel[T,2]`、`d_kf_x[T,7]`、`d_kf_P[T,7*7]`；
    - 计数：`d_track_count[1]`、`d_next_id[1]`。

- **k_ocsort_step 设计**
  - 单线程 kernel（`<<<1,1>>>`），核心步骤：
    1. 统一 `age++`；基于 `d_kf_x/d_kf_P` 预测轨迹框；  
    2. Stage1：对高分检测（score > det_thresh）构造 IoU+ReID+角度综合代价矩阵，调用匈牙利（GPU 版 `hungarian_minimize_device`）进行全局匹配；  
    3. Stage2：对未匹配轨迹与未匹配高分检测再做 IoU 匈牙利补充；  
    4. Stage2.BYTE：若开启 `use_byte`，对剩余轨迹与低分检测（low_score_thresh < s <= det_thresh）做 BYTE 风格 IoU 匈牙利匹配；  
    5. Stage3：对仍未更新轨迹与剩余高分检测做 IoU 匈牙利 rematch；  
    6. 为未匹配检测新建轨迹（初始化 Kalman/feat/age/hit_streak/missed）；  
    7. 对未匹配轨迹 `missed++`、`hit_streak=0`，按 `missed>max_missed` 压缩数组。
  - 为适配 sm_120 编译目标，内核内设置上限：
    - `MAX_TRACKS = 128`，`MAX_DETS = 128`，`MAX_N = 128`；
    - 所有本地矩阵（`cost_buf`、`cost_ext` 等）基于上述上限构建，以控制 per‑thread 栈消耗；在实际场景（T≈36、N≈10~20）远未触及该上限。

- **NodeTrackOcsort 行为**
  - `open()`：若 `USE_CUDA` 且存在 `ctx.gpu_pool && ctx.stream`，默认启用 `use_gpu_`，准备 GPU 状态。
  - `process()`：
    - 若 `use_gpu_` 为 true：
      - 调用 `process_gpu()`，成功则标记 `path=gpu` 并完全走 GPU 追踪；
      - 若失败（通过日志标记原因，如 `gpu_path_no_input_gpu_rois` / `gpu_state_alloc_failed` / `ocsort_match_and_update_failed err=X`），清理 `gpu_rois["track"]` 后回退 `process_cpu()`；
    - 若未启用 GPU，则直接走 CPU Deep OC-SORT 实现。
  - GPU 成功路径：只输出 `p.gpu_rois[out_rois_key_]`，由 `overlay.cuda(use_gpu_rois=1)` 直接消费；CPU `rois["track"]` 被清空。

---

## 四、当前状态与已知约束

- 已实现：
  - ReID & YOLO 节点通过 Triton In-Process 完成 GPU 输入 / 输出；
  - `roi.batch.cuda` 在 GPU 上生成 ReID 所需 `[N,3,384,128]` 输入；
  - OCSORT GPU 路径具备多阶段匈牙利与 BYTE 低分阶段，并在 sm_120 目标编译下稳定运行（`ms.track path=gpu` 无错误）。

- 已知约束：
  - 由于 CMake 目标架构设置为 `120`，必须控制内核本地内存；如需充分利用 RTX 5090D 的资源，建议后续在 CI/镜像中增加更高架构（如 `sm_89`）的编译配置；
  - CPU Deep OC-SORT 实现仍然是“行为金标准”，GPU 内核在复杂场景下的轨迹一致性仍需对比和迭代细化（特别是 CMC 与观测历史的影响）。

---

## 五、后续验证重点

1. 在静态/简单场景下对比 CPU/GPU 轨迹 ID 与框位置，确认匹配一致性；
2. 在遮挡、交叉、短时丢检的场景中观察 BYTE 阶段和 Stage3 的实际效果；
3. 长时间运行下验证 `OcsortGpuState` 与 GpuBufferPool 不出现显存泄漏或碎片问题；
4. 梳理 ReID/OCSORT/Triton 相关配置在 MinIO 与本地 Graph 中的一致性，确保后续变更可追溯。 
