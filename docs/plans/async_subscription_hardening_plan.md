# 异步订阅补强计划（Plan）

## 里程碑与验收

- M0｜接口与稳定性（P0，~1–2 天）
  - 内容：429+Retry-After、Location/ETag、reason_code 标准化；取消全路径清理；Windows `sock_t` 统一；前端“开始即取消”与阶段耗时微条。
  - 验收：
    - 队列满载返回 429+Retry-After；POST 返回 Location；GET 支持 ETag 命中 304。
    - 构建阶段取消后无泄漏/无崩溃；/metrics 指标齐全；UI 进度+阶段耗时可见。
- M1｜缓存/预热与恢复（P1，~1 周）
  - 内容：ModelRegistry/CodecRegistry（LRU+idle TTL）、预热名单、轻 WAL/Redis（重启后 in‑flight → failed(restart)）。
  - 验收：同一模型重复订阅 LoadingModel 明显下降；重启后恢复语义正确并产生告警。
- M2｜配额与可观测（P2，~1–2 周）
  - 内容：per-user/per-key 配额与拒绝策略；Grafana 面板（P95/失败率/队列/阶段耗时）和告警阈值；可选 Trace。
  - 验收：压测下配额生效；告警触发可靠；面板可用于容量规划。

## 任务分解（WBS）

1) 服务端（M0）
- 返回语义：429+Retry-After；Location 头；GET ETag/If-None-Match
- 取消清理：runSubscriptionTask 各阶段插取消点；RAII/finally 全覆盖
- reason_code：统一 `open_rtsp_error/load_model_error/pipeline_start_timeout/...`
- Windows 套接字别名：int→`sock_t`（SOCKET/‑1 统一 INVALID_SOCK）

2) 前端（M0）
- AnalysisPanel：
  - “阶段耗时”微条：RTSP/模型/启动；ready 后保留“上次构建用时”
  - 取消按钮：拿到 `subId` 即可用（构建阶段可取消）
- SSE 策略：重连退避（已具备），参数化重连上限

3) 监控与测试（M0）
- 指标核对：队列/在途/状态/完成/总时长/阶段耗时/失败原因
- Playwright MCP 场景（仅页面取证/JSON ≤10 字段）：
  - start→progress→timeline→ready/cancel，保存截图路径 tests/artifacts/*

4) 缓存/预热（M1）
- ModelRegistry：key=(model_hash, EP_opts)，LRU+idle TTL；失败路径安全回收
- 预热：启动后按名单并发预建（与当前负载限流互斥）

5) 恢复（M1）
- WAL/Redis：append-only 记录状态转移，重启恢复 in‑flight→failed(restart)
- 告警：重启窗口内 failed(restart) 总量阈值

6) 配额/可观测（M2）
- 配额：per-user/per-key（源/模型/并发数/GPU），超限拒绝
- 面板/告警：P95 时延、失败率、队列长度、阶段耗时
- Trace（可选）：open_rtsp/load_model/start_pipeline/whep 几个 span

## 时序与资源

- 负责人：后端×1，前端×1，QA×0.5（MCP 驱动）；运维×0.3（Grafana/告警）
- 时间：M0=2d，M1=5d，M2=7–10d（可并行压测与面板）

## 风险与缓解

- 取消清理不全 → 全路径 RAII + 单测/压测覆盖 + 代码审查
- 缓存污染/内存膨胀 → LRU+idle TTL，失败即丢弃并计数告警
- WAL/Redis 不可用 → 降级仅日志；恢复语义标注失败即可
- SSE 断流 → keep‑alive + Last-Event-ID + 回退轮询；前端退避策略
- Windows 套接字崩溃 → `sock_t` 统一，增加 e2e soak 校验

## 验收清单（抽样）

- 429/Retry-After/Location/ETag/304 行为符合预期
- include=timeline 含 8 个阶段时间戳，前端“阶段耗时”显示正确
- 并发 N=50/100，24h soak 无句柄/内存泄漏；失败率与 P95 在阈值内
- 重启后 in‑flight→failed(restart) 可见；告警触发
- 配额拒绝策略与提示文案清晰
