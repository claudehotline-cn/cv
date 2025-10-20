# 路线图总览
- **M0 骨架上线**：完成 SubscriptionManager 骨架、REST 路由占位、文档对齐 → 验收：API 返回订阅 ID 与阶段 JSON，原 /api/subscribe 正常；构建通过
- **M1 异步任务落地**：接入真实 RTSP/模型/管线阶段，完善限流/取消 → 验收：阶段日志齐全，重资源信号量生效，Ready率≥80%，失败原因可溯
- **M2 前端与监控联调**：前端消费新接口、SSE/轮询进度，Prometheus 指标可用 → 验收：UI 可展示进度与错误，指标面板展示阶段耗时/排队长度/失败率

# 分阶段计划
| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| P0 骨架 (已完) | SubscriptionManager 占位、POST/GET/DELETE /api/subscriptions、设计/计划文档 | 状态表、任务队列、幂等键、基础限流接口 | 结构未实用 → 保留旧接口、禁用外部入口 | 构建通过、API 202 响应正确 |
| P1 实装异步 | 接入实际阶段、限流/取消、错误原因、状态清理 | RTSP 探测、模型加载、Pipeline 启动、信号量/超时、状态持久化 | 重资源争用 → 信号量、退避；取消失败 → 统一回滚 | Ready≥80%，失败原因覆盖≥90%，取消成功率≥95% |
| P2 前端+观测 | 前端进度 UI、SSE/轮询、Prometheus 指标、告警 | Pinia/Vue 适配、SSE/轮询容错、指标上报、告警阈值 | 前端滞后 → Feature flag 灰度；指标缺失 → 提前校验 | UI 展示完整阶段，指标面板上线，告警测试通过 |

# 依赖矩阵
- 内部依赖：Application::subscribeStream/unsubscribeStream、TrackManager、PipelineBuilder、WHEP Session、Sessions/Event/Log Repo
- 外部依赖（库/服务/硬件）：FFmpeg/RTSP 源、ONNX Runtime、CUDA/NVDEC/NVENC（可选）、MySQL、Prometheus/Grafana

# 风险清单（Top-5）
- 任务状态紊乱 → 并发/锁使用不当 → 阶段错乱或重复订阅 → 单元测试 + 幂等校验 → 遇到异常立即下线到旧接口
- 重资源耗尽 → 多任务同时加载模型/RTSP → GPU/网络占满 → 信号量 + 退避策略 → 触发阈值时暂停新任务并告警
- 取消失败 → Pipeline 挂残留 → metrics/资源泄漏 → 统一回滚 + 定期清理 → 设置背景巡检与超时终止
- 前端未同步 → 用户界面卡在 Pending → 实装前端 feature flag 灰度 → 提供降级开关回到旧接口
- 指标缺失 → 无法监控延迟/失败 → 未部署 Prometheus exporter → 指标门控在 M2 验收中，未达标不切流量
