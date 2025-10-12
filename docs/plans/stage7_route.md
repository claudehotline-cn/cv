# 阶段7 GPU 推理增强实施路线图

## 总体目标
- 让后端在 GPU 下具备稳定的 IOBinding 数据管线，消除 CPU↔GPU 往返拷贝。
- 打通 TensorRT Execution Provider，解决 CUDA EP 缺算子导致的 `cudaErrorNoKernelImageForDevice` 问题。
- 暴露推理设备与性能状态，支持按需回退与监控告警。
- 为后续 WHIP/WHEP 及其它 GPU 优化预留统一扩展点，同时保持现有 REST/WebRTC 行为兼容。

## 前置条件
- 已成功构建 ONNX Runtime 1.23.0 GPU 版（含 CUDA 12.9 support）。
- `video-analyzer` 运行时目录完整，已放置自编译 ORT/TensorRT/FFmpeg DLL。
- 深度重构阶段 1~6 的接口拆分与日志体系已就绪。
- 配置体系（YAML）已支持新版 Analyzer/Engine 结构，可继续追加字段。

## 实施步骤

### 1. IOBinding 管线落地
- **配置扩展**：在 `InferenceConfig` 增加 `use_io_binding`、`gpu_buffer_shape/size` 等字段，在 `AppEngineSpec` 与 `ConfigLoader` 中解析。
- **Session 初始化**：`OnnxRuntimeBackend` 在启用 GPU 时创建 `Ort::IoBinding`，预先分配 pinned host / device buffer。
- **推理调用**：`infer()` 根据配置选择 Input/Output binding，并在 CUDA EP 下复用 GPU 缓冲区；保留 CPU fallback。
- **验证**：在启用 IOBinding 时记录日志（数据从 GPU buffer 读取），并通过手工脚本比较 CPU/GPU 结果一致性。

### 2. TensorRT Execution Provider 集成
- **YAML 扩展**：为模型/引擎配置新增 `provider: tensorrt|cuda|cpu`，支持设置 FP16/INT8、工作空间大小等。
- **EngineManager**：加载时优先尝试 TensorRT，失败自动回落 CUDA→CPU，记录原因。
- **ONNX Runtime 配置**：在 `OnnxRuntimeBackend::configureCUDA()` 内，根据 provider 选择 `AppendExecutionProvider_TensorRT` 并处理所需选项（`trt_fp16_enable` 等）。
- **模型兼容性校验**：启动时检查 TensorRT build 日志，将失败算子、层名称写入诊断输出。
- **验证**：通过现有脚本 + 新增性能对比脚本（记录推理耗时、GPU 利用率），确认 TensorRT 能跑通 YOLOv12。

### 3. Provider 与设备状态治理
- **状态模型**：在 `EngineManager` 维护当前 Provider、IOBinding 状态、最近错误信息。
- **API 暴露**：更新 `/api/system/info`、`/api/models` 返回 `execution_provider`、`io_binding`、`fallback_reason` 等字段。
- **前端适配**：在视频分析面板展示当前推理模式，必要时给出提示（如自动回退 CPU）。
- **日志规约**：统一 GPU 相关日志前缀，避免刷屏；必要时支持按需降级日志级别。

### 4. 预留扩展点（WHIP/WHEP & 其它 GPU 优化）
- **接口预留**：在 `ITransport`、`PipelineBuilder` 中加入 WHIP/WHEP 占位实现（返回 `NotImplemented`），并在配置中允许声明但不启用。
- **IOBinding 扩展**：设计接口允许未来加入 NVDEC/NPP 等硬件加速前处理，确保数据结构兼容。
- **文档同步**：在 `docs/development_notes.md` 补充扩展点说明及启用方式。

### 5. 测试与监控
- **脚本扩展**：在 `scripts/` 下新增 `check_gpu_inference.py`，对开启 CUDA/TensorRT 的 REST+WebRTC 流程做端到端校验。
- **性能回归**：记录基线吞吐（FPS）、单帧延迟，压测脚本接入 `VideoAnalyzer` 日志，自动判断是否退化。
- **报警点**：定义日志/metrics 字段，后续可对接 Prometheus；先在日志中输出 JSON 行便于收集。

## 交付节奏
1. **迭代 A**：完成 IOBinding 配置与实现，保持默认关闭，验证 GPU 流程。
2. **迭代 B**：加上 TensorRT provider 及回退策略，文档说明差异。
3. **迭代 C**：补充 API/前端展示与测试脚本，整理监控输出。

每个迭代结束需打标签记录提交，并运行 `check_subscription_flow.py` + 新增 GPU 测试脚本确认通过。

## 风险与应对
- **算子不支持**：如果 TensorRT 对 YOLOv12 仍缺算子，保持自动回退及禁用选项；必要时引入插件或将 QuickGelu 替换。
- **内存管理复杂度**：IOBinding 缓冲区管理需覆盖分辨率变化、模型切换；建议在 `Pipeline` 中监听尺寸变化并重建绑定。
- **兼容性**：确保 Windows + CUDA 12.9 下的 ORT/TensorRT 版本一致，必要时在文档列出具体 DLL 列表。

## 验收标准
- 打开 `use_io_binding` 时 GPU 推理可稳定运行，无额外 CPU 拷贝。
- 指定 `provider: tensorrt` 后能自动选择 TensorRT，失败时记录回退原因并继续推理。
- `/api/system/info` 返回准确的执行后端信息，前端可实时展示。
- 新增脚本与现有脚本全部通过；Release 构建无新增警告。

