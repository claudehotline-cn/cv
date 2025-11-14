# 推理引擎与多阶段 Graph 设计文档索引

本目录归类“推理引擎、多阶段 Graph 与零拷贝执行路径”等相关设计文档。

- 引擎与推理会话
  - [TensorRT 引擎设计](./tensorrt_engine.md)
  - [Triton gRPC 集成设计](./triton_integration_design.md)
  - [Triton In-Process 集成设计](./triton_inprocess_integration.md)
- 多阶段 Graph 框架与节点
  - [多阶段 Graph 详细设计](./multistage_graph_详细设计.md)
  - [多阶段 Graph 条件边与 join 使用指南](./多阶段Graph条件边与join使用指南.md)
  - [多阶段 ReID 平滑节点](./多阶段ReID平滑节点.md)
- 执行路径与性能
  - [GPU 零拷贝执行路径详细设计](./zero_copy_execution_详细设计.md)
  - [性能保护与 Guard（如有）](./perf_guards.md)
