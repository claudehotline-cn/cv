# M1/M2 任务与代码入口

本清单用于跟踪 M1（WAL 与预热收尾）与 M2（配额/ACL 与压测）的后续任务，并给出对应的代码入口（文件/位置）。

## M1（收尾）
- [ ] 指标：WAL 维度标签（谨慎控制 cardinality）
  - 入口：`video-analyzer/src/server/rest_metrics.cpp`:190 附近（WAL 与订阅指标区）。
- [ ] 预热失败计数来源从骨架改为真实错误路径
  - 入口：`video-analyzer/src/analyzer/model_registry.cpp` 中 `runPreheat()`；失败时 `failed_total_++`。
- [ ] ETag 竞态更完整覆盖（已增并发脚本，后续扩展更多状态切换）
  - 脚本：`video-analyzer/test/scripts/check_etag_race.py`。
- [ ] Grafana 大盘完善（按实际场景扩展源级维度与面板）
  - 文件：`docs/references/grafana/va_dashboard.json`。

## M2（配额/ACL 与压测）
- [ ] 配额与节流（并发/速率）
  - 入口：`video-analyzer/src/server/rest_subscriptions.cpp`（创建入口）、`video-analyzer/src/server/subscription_manager.hpp/.cpp`（统计在途 by requester_key）。
  - 配置：`video-analyzer/config/app.yaml` 的 `quotas.*`。
  - 指标：新增 `va_quota_dropped_total{reason=...}`（`rest_metrics.cpp`）。
- [ ] ACL 校验（允许的 scheme/profile）
  - 入口：`rest_subscriptions.cpp`（创建参数校验）。
- [ ] 压测与 soak（N=50/100，24h）
  - 工具：可扩展 `tools` 目录脚本或引入独立压测脚本。
  - 结果：P95/失败率达标，内存/句柄无异常，记录至 memo。

## CI/可观测
- [ ] 将 Smoke 扩展到主分支（如需要修改工作流触发分支）。
- [ ] 增加夜间定时触发与 artifacts（日志/WAL 片段）。

