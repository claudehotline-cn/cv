# 路线图总览

- M0｜异步订阅与稳定播放：新建 `/api/subscriptions*` 与 SSE；前端统一 `createSubscription + SSE`，播放刷新不崩溃；基本指标上线。
  - 验收：Start→Ready 可复现；取消可用；刷新稳定；/metrics 含队列、状态、完成计数与总时长直方图。
- M1｜可靠性与可运维：配置（ttl/slots/queue）YAML 化并回显来源；Sources SSE 启用；失败原因标准化与面板；E2E 用例与 CI。
  - 验收：System Info 展示来源与生效值；失败原因图可读；CI 3 条 E2E 稳定通过；旧接口默认 410。
- M2｜规模化与长稳：分阶段限流调优（rtsp/model）；并发 N=50/100 与 24h 压测；SSE Last-Event-ID 与时间线；Grafana 告警完善。
  - 验收：P95 订阅耗时达标（阈值可配）；失败率 <1%；SSE 断线重连稳定；面板/告警覆盖完整。

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| P0 | 订阅 API+SSE+播放稳定 | /api/subscriptions*、SSE keepalive、WHEP 刷新清理 | 会话泄漏→双清理 | 刷新0崩溃 |
| P1 | Sources SSE 与失败原因 | /api/sources/watch_sse、原因标准化与指标 | 代理超时→keepalive | 失败原因可见 |
| P2 | 配置 YAML 化 | ttl/slots/queue 配置与 env 覆盖、来源回显 | 配置漂移→来源标注 | 配置稳定加载 |
| P3 | E2E+CI | 三条用例脚本与 Actions | 选择器脆弱→语义选择 | CI 通过 |
| P4 | 时间线与 Last-Event-ID | GET include=timeline、SSE id/retry | 重连丢事件→对齐 | 无丢/乱序 |
| P5 | 并发与长稳压测 | N=50/100、24h；slots 调优 | 资源枯竭→限流配额 | 失败<1% |
| P6 | 告警与面板完善 | P95、失败率、队列、原因面板 | 指标缺口→补采样点 | 告警有效 |

# 依赖矩阵

- 内部依赖：
  - VA（订阅/SSE/指标/WHEP）；CP（内嵌控制）；VSM（源管理）；前端（store/视图/E2E）。
- 外部依赖（库/服务/硬件）：
  - Prometheus/Grafana、MySQL；ffmpeg/mediamtx（RTSP）；libdatachannel（WebRTC）；GPU 驱动与 ONNX/TensorRT（可选，CPU 回退）。

# 风险清单（Top-5）

- SSE 断流 → 网络波动/代理超时 → 事件间隙/无心跳 → keepalive+Last-Event-ID+轮询兜底。
- 并发枯竭 → 模型/RTSP 吞吐不足 → 失败率升高 → 分阶段限流+配额与回退。
- 会话泄漏 → 刷新/崩溃未清理 → 句柄/内存增长 → 浏览器 keepalive + 后端 Closed/Failed 自清理 + TTL。
- 配置漂移 → 多来源不一致 → 行为不可预测 → YAML+env 覆盖策略与来源回显。
- 观测缺口 → 原因/阶段不可见 → 诊断困难 → 失败原因标准化+时间线与阶段直方图。
