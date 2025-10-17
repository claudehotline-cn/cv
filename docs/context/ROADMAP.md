# 路线图总览

- M0「DB 与控制面打通」
  - 目标：VA REST 全面 DB-only 与分页过滤稳定；控制面 Apply/HotSwap/Drain/Remove 联通；VSM 基础源管理与 SSE。
  - 验收：/api 日志/事件/会话 200/503 语义一致；控制面路由 E2E 可用；VSM /api/source/* 可用，SSE 正常。
- M1「可观测与编排」
  - 目标：/metrics 增强（va_cp_*、DB/Writer/Retention）；Drain 可观测（blocked_nodes/reason）；VSM↔VA 编排；前端 Orchestration 页与健康卡片。
  - 验收：va_cp_requests_total/直方输出正确；status.drain 字段齐全；/api/orch/* 成功率>99%；前端可执行 Attach+Apply/Detach+Remove 并展示健康摘要。
- M2「精细化与稳健性」
  - 目标：每 pipeline 编码器回压、节点自省扩面；前端自动化取证完善；错误语义/超时与重试全面一致化。
  - 验收：pipeline 级回压指标接入 Drain，前端可定位；Playwright 场景稳定；4xx/5xx/重试策略文档化与落地。

# 分阶段计划（表格）
| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| M0 | VA DB-only + 控制面 | 分页/过滤；Apply/HotSwap/Drain/Remove | DB/IO 超时 → 设置收发超时；503 语义一致 | REST P95<200ms(1k行) |
| M0 | VSM 基础源管控 | list/add/update/delete/watch/SSE | SSE 阻塞 → 发送超时+并发上限 | SSE 拒绝率<1% |
| M1 | 控制面指标 | va_cp_requests_total + 直方 | 高并发统计开销 → 轻量聚合 | 统计丢失<1% |
| M1 | Drain 可观测 | 编码器回压+节点自省聚合 | 误判 → 多信号交叉验证 | 误报<5% |
| M1 | 编排与健康 | /api/orch/*、前端 Orchestration | 超时 → SNDTIMEO/重试 | 成功率>99% |
| M2 | pipeline回压 | TrackMgr 导出按流计数 | 侵入性 → 只读接口 | 状态更新<1s |
| M2 | 前端自动化 | Orchestration E2E 取证 | 预览缓存 → 构建+重启脚本 | 取证通过率>99% |

# 依赖矩阵
- 内部依赖：
  - video-analyzer（REST/metrics/控制面/Drain 聚合）
  - video-source-manager（源管理/编排/健康/metrics）
  - web-front（Orchestration/Observability）
- 外部依赖（库/服务/硬件）：
  - MySQL 8.x + mysqlsh（DB-only 路由与取证）
  - Prometheus 文本规范 0.0.4（/metrics）
  - Element Plus、Vite、Playwright（前端与自动化）
  - GPU（NVDEC/NVENC 可选，需 CPU 回退）

# 风险清单（Top-5）
- 路由阻塞 → 长连接/SSE/慢查询 → P95 飙升 → 收发超时+分离锁 → 观测 cp/DB 队列。
- 误判回压 → 单一信号不稳 → 错误诊断 → 合并多指标（回压+截断+失败）。
- 预览缓存 → 新路由 404 → 取证失效 → 构建+预览重启脚本与强刷提示。
- 编排耦合 → VSM→VA 失败链 → 不一致状态 → 超时重试+幂等+健康接口校验。
- 错误语义不一 → 诊断困难 → 统一 400/404/409/503 与 warnings 文档化。
