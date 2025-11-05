# 范围与目标

- 范围：在 VA 中完善 ORT TensorRT/RTX EP 选择与回退；新增原生 TensorRTModelSession；统一 CUDA 流与零拷贝输出；Docker/构建与可观测性
    配套。
- 目标：在 RTX 5090D（SM_120）上优先使用 TensorRT‑RTX EP，性能不低于 CUDA EP；阶段二实现原生 TRT 会话并稳定上线。

  分阶段 WBS

- M0 工厂与 EP 选择（1–2 天）
  - 需求澄清与验收
    - 明确 provider 优先级：tensorrt-rtx → tensorrt → cuda → cpu
    - 验收：outputs>0、日志含 provider_resolved、720p ≥30FPS（CUDA EP 基线）
  - 代码改造
    - 新增 model_session_factory.hpp/.cpp（工厂创建 IModelSession）
    - 修改 node_model.cpp 使用工厂注入 IModelSession
    - 扩展 OrtModelSession：追加 NV TensorRT RTX EP、TRT EP 的 provider 附加与选项映射（fp16/workspace/stream）
  - 构建/容器
    - Dockerfile.gpu：确保 ORT 1.23.2 源构建产出 providers_tensorrt/providers_nv_tensorrt_rtx；补全 libonnxruntime.so/.so.1
    - LD_LIBRARY_PATH 注入；24 线程并行
  - 可观测与测试
    - 日志：load/run 阶段输出 provider_req/resolved、in/out、shapes、io_binding
    - 脚本验证：check_onnx.py；端到端订阅 + pipeline_mode 切换；指标帧数递增
  - 交付物
    - 工厂与改造代码、Docker 镜像、日志样本、测试记录
- M1 原生 TensorRT 会话（2–4 天）
  - 会话实现
    - 新增 trt_session.hpp/.cpp：解析 ONNX（nvonnxparser）→ 构建 ICudaEngine/IExecutionContext
    - 统一 CUDA 流：接收 user_stream；使用 enqueueV2/V3
    - 内存与绑定：设备输入/输出绑定；device_output_views=true 时直接暴露 device tensor
  - CMake/依赖
    - find_path/find_library 检测 NvInfer/nvonnxparser；-DUSE_TENSORRT 控制编译与链接
    - 性能对比：CUDA EP / TRT EP / TRT‑RTX EP / TRT‑Native（720p ≥30FPS）
  - 交付物
    - TensorRTModelSession 代码、CMake 变更、运行与性能报告
- M2 动态 Profile 与引擎序列化（3–5 天）
  - 动态与缓存
    - 支持动态 profile（常见输入分辨率）；plan 序列化缓存与哈希校验
    - 预热：加载后进行 dummy 轮推理降低首帧延时
  - 可观测性
    - 增加显存与耗时指标；对比 P50/P95；故障注入回退验证
  - 回归与文档
    - 全量回归：暂停/恢复、换模、订阅生命周期
    - 完善设计/运维文档与 CI 钩子
  - 交付物
    - 动态/序列化能力、指标仪表、回归报告与文档

  工作包细化与依赖

- WP1 工厂与抽象
  - 任务：定义 IModelSession 接口；实现工厂；NodeModel 接入
  - 依赖：无
  - 依赖：WP2（验证 providers 库产出）
  - 验收：/opt/onnxruntime/lib 下 providers_* 存在；ldd 解析正常
- WP4 原生 TRT 会话
  - 任务：解析/引擎/上下文/绑定/统一流；设备视图输出
  - 依赖：WP1, WP3（TRT 依赖）
  - 验收：端到端 outputs>0，行为一致
- WP5 动态/序列化与调优
  - 任务：profile/plan 缓存/预热；指标与回归
  - 依赖：WP4
  - 验收：冷启动<3s；720p ≥30FPS；回归通过

  时间与角色建议

- 时间：M0 1–2 天，M1 2–4 天，M2 3–5 天（并行度视硬件/镜像构建速度调整）
