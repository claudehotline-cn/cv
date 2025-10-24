# 路线图总览

- M0｜接口稳定性与可观测基线（已起步）
  - 目标：统一 REST 语义（POST 202+Location、GET ETag/304），提供系统/全局基础指标，构建与运行脚本稳定。
  - 验收标准：headers+cache 脚本通过；/metrics 基础指标可抓取；订阅 GET 命中 304；构建与启动一次成功。
- M1｜WAL 与注册表预热（进行中）
  - 目标：接入 WAL 持久化与重启扫描、模型/编解码注册表预热、将状态/指标对外曝光。
  - 验收标准：/api/system/info 暴露 wal/registry.preheat 字段；/metrics 出现 va_wal_failed_restart_total；WAL 文件滚动与 TTL 生效；重启后 inflight 近似统计可用。
- M2｜配额/ACL 与压测可视化（规划）
  - 目标：配额/ACL 生效并可观测；Grafana 大盘；N=50/100 压测与 24h soak 通过；P95/失败率等门槛达标。
  - 验收标准：P95 达标、失败率低于阈值；大盘覆盖关键链路；长时间运行无崩溃与资源泄漏。

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| M0 | REST 语义统一；拆分大文件；基础指标；脚本化校验 | POST 202+Location；GET ETag/304；rest.cpp 模块化；基线指标 | 链接占用→先停再构建；SSE 异常→心跳/限速 | headers+cache 通过；/metrics 可抓取；构建通过 |
| M1 | WAL + 预热 + 状态曝光 | WAL init/mark_restart/scan；注册表预热；/system/info & /metrics 暴露 | 文件滚动/锁竞争→加锁与 size/TTL 滚动；预热耗时→并发上限 | /system/info 含 wal/registry；va_wal_failed_restart_total 可见 |
| M2 | 配额/ACL；Grafana；压测/soak | per-key/GPU 配额/节流；ACL 配置/验证；Grafana 面板；压测脚本 | 规则误杀→灰度豁免；高并发→背压降级 | P95、失败率达标；24h soak 0 崩溃/无泄漏 |

# 依赖矩阵

- 内部依赖：
  - video-analyzer（VA）、control_plane_embedded、video-source-manager（VSM）、web-frontend（可视化与 E2E）。
- 外部依赖（库/服务/硬件）：
  - WinSock/Windows SDK；ONNX Runtime/TensorRT；FFmpeg/mediamtx；Prometheus/Grafana；MySQL（Connector/C++）；libdatachannel；NVIDIA GPU（NVDEC/NVENC）。

# 风险清单（Top-5）

- SSE/连接管理不稳 → 长连接堆积或异常关闭 → 事件频率异常、FD 数上涨 → 心跳+限速+空闲超时+连接上限，必要时降级为长轮询。
- 资源泄漏/内存增长 → 压测或 soak 中常驻内存爬升 → RSS/句柄异常 → 引入内存/FD 监控，阶段性压测与快照比对，回滚可疑改动。
- 指标缺口/不一致 → 阶段直方图、失败原因缺失 → /metrics 值为 0 → 增量补齐指标，统一枚举与标签，脚本对齐校验。
- 预热抖动 → 大量模型/编解码预热耗时 → 启动延时 → 异步预热+并发上限+LRU/TTL；/system/info 暴露进度与错误。
- 过载与 429 策略 → 突发流量导致队列饱和 → 响应变慢/错误率升高 → 背压与 Retry-After；配额分级（M2）；压测阈值接入告警。