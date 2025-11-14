## Triton 集成（M0–M2）
- [ ] 设计评审与范围确认（docs/design/engine_multistage/triton_integration_design.md）
- [ ] WBS 对齐（docs/plans/triton_wbs.md）
- [ ] T0 功能（gRPC + Host 内存）
  - [ ] 新增 `TritonGrpcModelSession`（IModelSession 实现）
  - [ ] 工厂映射 `engine.provider=triton|triton-grpc`
  - [ ] 单路 720p E2E boxes>0 验证
- [ ] 可观测与回退链对齐
  - [ ] 指标 `va_triton_rpc_seconds`/`va_triton_rpc_failed_total`
  - [ ] Triton 不可用时回退至 ORT-TRT→CUDA
- [ ] 配置与 Compose 支持
  - [ ] docker compose 新增 `triton` 服务与模型仓库映射
  - [ ] VA 示例配置（engine.options.triton_*）
- [ ] T1 性能（CUDA SHM 输入/输出）
  - [ ] SHM 注册/复用/重注册；设备侧 TensorView 输出
  - [ ] 统一流同步与安全消费
- [ ] T2 深化（动态形状/批量/Ensemble可选/熔断）
- [ ] 基准与报告（填充 docs/plans/benchmark-report-template.md）

