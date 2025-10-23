# 路线图总览

- M0｜接口稳定性与可观测基线（已起步）
  - 目标：REST 语义统一（POST 202+Location、GET ETag/304）、最小可观测性（系统/全局指标）、E2E 校验与构建稳定。
  - 验收标准：headers+cache 测试通过；/metrics 基础指标可见；构建/运行脚本稳定；订阅 GET 304 生效。
- M1｜WAL 与注册表预热
  - 目标：WAL 重启恢复、Model/Codec Registry 预热与状态曝光、控制面指标完善（失败原因/耗时直方图）。
  - 验收标准：重启后 inflight 状态不丢；/api/system/info 暴露预热状态；/metrics 出现 failed(restart)、inflight 时长直方图。
- M2｜配额/ACL 与压测可视化
  - 目标：配额/ACL 控制与告警、Grafana 大盘、P95/失败率门槛、24h soak 稳定运行。
  - 验收标准：P95/FPS/失败率达标；大盘与告警覆盖关键链路；长时间 soak 无资源泄漏与崩溃。

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| M0 | REST 语义统一；拆分大文件；基础指标；脚本化校验 | POST 202+Location、GET ETag/304；server/rest.cpp 模块化；/metrics 基线 | 链接被占用→先停再构建；SSE 异常→保活与限速 | headers+cache 通过；/metrics 可抓取；构建成功 |
| M1 | WAL/Registry 预热；状态曝光；控制面直方图 | WAL 扫描与 TTL；Model/Codec LRU+idle TTL；/api/system/info 预热字段；CP 请求耗时直方图 | 重启竞态→加锁与去重；预热耗时→异步与限速 | 重启恢复率≈100%；failed(restart) 指标就绪 |
| M2 | 配额/ACL；Grafana 大盘；压测/soak | per-key/GPU 配额与节流；ACL 配置/验证；Grafana 面板与告警；N=50/100 压测 | 规则误杀→灰度与豁免；高并发→背压与降级 | P95/失败率门槛达标；24h soak 0 崩溃/无泄漏 |

# 依赖矩阵

- 内部依赖：
  - video-analyzer（VA）；control_plane_embedded（内嵌控制器）；video-source-manager（VSM）；web-frontend（预览与可视化）。
- 外部依赖（库/服务/硬件）：
  - WinSock/Windows SDK；ONNX Runtime/TensorRT；FFmpeg/mediamtx；Prometheus/Grafana；MySQL（Connector/C++）；libdatachannel；NVIDIA GPU（NVDEC/NVENC）。

# 风险清单（Top-5）

- SSE/连接管理不稳 → 长连接堆积或异常关闭 → 事件频率异常、FD 数上涨 → 限速+心跳+空闲超时+连接上限，必要时降级为长轮询。
- 资源泄漏/内存增长 → 压测或 soak 中常驻内存爬升 → RSS/句柄/GC 指标异常 → 引入内存/FD 监控，分阶段压测与快照比对，回滚可疑改动。
- 指标不一致/缺口 → 阶段直方图/失败原因缺失 → /metrics 缺字段或为 0 → 增量补齐指标，统一标签与枚举，测试脚本比对。
- 预热/注册表抖动 → 大量模型/编解码预热耗时 → 启动时间过长或阻塞 → 异步预热+并发上限+LRU/TTL；/api/system/info 暴露进度与错误。
- 过载与 429 策略 → 队列饱和/突发流量 → 响应耗时陡增、错误率上升 → 背压与 Retry-After；分级限流与配额（M2）；压测发现阈值并写入告警。