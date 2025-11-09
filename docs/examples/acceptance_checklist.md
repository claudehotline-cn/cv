## 验收清单（P7）

最小验收（Smoke / 10 分钟）
- Controlplane 启动，HTTP 可达：`GET /api/ui/schema/engine` 返回 OK
- 指标可达：`GET /api/_metrics/summary` 返回请求/错误/缓存统计
- VA 运行态：`GET /api/va/runtime` 返回 provider（triton）且 `gpu_active` 与期望一致

性能小验收（30 分钟）
- 开启 VA gRPC 端口（In‑Process）：`triton_enable_grpc: true`
- 运行 perf：`tools/triton/perf_analyze.sh -m <model> -u localhost:8001 -c 1,2,4,8 --protocol grpc --report perf.csv`
- 生成推荐批次：`tools/triton/suggest_dynamic_batch.py --report perf.csv --latency-budget-ms 2.0`
- 更新 `config.pbtxt` 后复测，P90 在预算内吞吐提升

稳定性（长稳基线）
- 单路 RTSP 连续运行 ≥ 24 小时：
  - 无崩溃与 30s 关停等待日志
  - 显存/时延曲线无持续爬升
  - 控制/切换（HotSwap 或 RepoLoad）操作过程无中断

回滚/灰度
- `va_release` 切换模型后，异常时可回滚至上一版本
- 可选：以 `ens_*` 作为发布别名，底层子模型/版本切换对调用侧透明

