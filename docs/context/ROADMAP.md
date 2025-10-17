# 路线图总览

- M0「DB 落地与稳定」
  - 目标：后端改为 DB-only，无回退；日志/事件/会话支持分页、时间窗与过滤；/metrics 与保留任务可观测；前端提供 DB 视图基础能力。
  - 验收标准：/api 日志/事件/会话接口在 DB 正常时 200、异常时 503 且前端可见错误；/metrics 暴露连接池、Writer 队列、Retention 指标；Logs/Events/Sessions DB 视图可分页与导出。
- M1「可观测性完善」
  - 目标：前端 Metrics 页提供关键指标卡片与趋势；DB 视图支持服务端分页与多值过滤；稳定性脚本与取证完善。
  - 验收标准：指标卡片有阈值高亮；趋势可导出 CSV；多值过滤（node/stream_id CSV）与分页取证通过；脚本一键启停/探测可复用。
- M2「控制平面与性能治理」
  - 目标：控制平面（Apply/Status/HotSwap）完善；索引与队列压测达标；/metrics 覆盖率提升并用于告警阈值验证。
  - 验收标准：HotSwap 与 Apply 回路 E2E 成功；批量插入 + 查询耗时证据齐全；关键指标波动在设定阈值内。

# 分阶段计划（表格）
| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| M0 | DB-only REST、分页/过滤、基础指标 | CSV→SQL IN；分页 total；非阻塞 /metrics 快照；WinSock 超时 | DB 不可用时误阻塞 → 明确 503 与前端告警 | 查询 P95 < 200ms（1k 行） |
| M0 | 前端 DB 视图与导出 | 服务端分页；日期变更重置页码；CSV 导出 | Vite 预览陈旧切片 → 提供重启脚本 | 首屏 < 2s、翻页 < 500ms |
| M1 | Metrics 卡片与趋势 | 轮询 /metrics；阈值高亮；CSV | 指标漂移 → 固定采样与单位 | 采样丢失率 < 1% |
| M1 | 取证与脚本化 | probe_api、前端取证、mysqlsh 脚本 | 环境差异 → 配置集中化 | 证据完整、可复现 |
| M2 | 控制平面与压测 | HotSwap/Apply 路由；索引压测 | 链接占用/LNK1104 → 构建前停止进程 | 压测提升≥30% |

# 依赖矩阵
- 内部依赖：
  - `video-analyzer`（REST、/metrics、控制平面、DB Pool/Repos）
  - `web-frontend`（DB 视图、Metrics、Settings）
  - `video-source-manager`（SSE/LIVE 链路，独立可选）
- 外部依赖（库/服务/硬件）：
  - MySQL 8.0（端口 13306）、MySQL Shell 8.4
  - Prometheus 指标规范 0.0.4
  - Element Plus、Vite、Playwright MCP
  - GPU/解码器（NVDEC）可选，需 CPU 回退

# 风险清单（Top-5）
- DB 连接池耗尽 → 高并发/慢查询 → 请求堆积、P95 飙升 → 增大池、限流与查询超时、优化索引。
- SSE 长连影响其他路由 → 发送阻塞/锁粒度过大 → 其他 REST 超时 → 发送超时与去锁化，SSE 独立队列。
- 配置/环境漂移 → 端口/配置目录不一致 → 503 或数据缺失 → 统一配置源并在 /system/info 回显。
- 指标不一致/缺失 → 采样与单位差异 → 趋势异常或告警失效 → 统一采样窗口与单位，导出校验样本。
- 构建期占用（LNK1104） → 进程未关闭 → 构建失败 → 构建前停止进程，脚本自动重启。
