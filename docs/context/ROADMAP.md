# 路线图总览
- M0｜基础贯通
  - 目标：VA/VSM 启停稳定；/analysis 可获取 Sources/Graphs；WHEP 握手 201/Location；订阅 400 有兜底。
  - 验收：/api/system/info 与 /api/source/list 200；/api/graphs 来自 DB；前端选择 det_720p+camera_01 能出画（首帧 ≤3s）。
- M1｜可观测与取证
  - 目标：/metrics 暴露 WHEP/CP 指标；前端 UI 自动化取证；错误提示友好。
  - 验收：保存一次 /analysis 播放取证 JSON；WHEP/CP 指标出现在 Metrics 页卡；订阅失败提示含具体原因。
- M2｜稳定与扩展
  - 目标：多实例路由稳定（VA_GRPC_HOSTS）；Graphs/Models/Pipelines 均可 DB 管理；回滚与灰度策略。
  - 验收：8 路并发 30min 无异常；DB 与 UI 一致；发生异常可一键回滚。

# 分阶段计划（表格）
| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| P0 | /api/graphs 改 DB-only | GraphRepo + REST 切换；前端映射 id/name/requires | 结构差异→前端适配 | 下拉=DB 实际数 |
| P1 | 订阅兜底与错误提示 | startAnalysis 默认值+重试；ElMessage 细化 | 误判→只重试一次 | 首帧≤3s 成功率≥95% |
| P2 | WHEP/CP 指标 | /metrics 增 WHEP 会话与 CP 直方 | 性能开销→聚合/抽样 | 指标可见且稳定 |
| P3 | UI 取证 | Playwright E2E（首帧/摘要） | 首屏慢→延长等待/重试 | 证据文件完整 |
| P4 | 多实例路由稳态 | gRPC 路由、TTL/GC、错误回退 | 连接抖动→本地回退 | 并发 8 路 30min |

# 依赖矩阵
- 内部依赖：
  - VA 控制面与媒体（WHEP、订阅）、存储层（DbPool/Repos）、REST 路由。
  - VSM 源聚合（REST）、gRPC 编排（Attach/Detach）。
- 外部依赖（库/服务/硬件）：
  - MySQL 8.x（cv_cp，端口 13306）；mysql-connector-c++。
  - libdatachannel（WHEP）；NVIDIA CUDA/NVDEC/NVENC（可选）。

# 风险清单（Top-5）
- 订阅 400 → profile/uri 缺失 → 前端兜底/校验 + 后端返回结构化错误 → 前端只重试一次
- WHEP 失败 → 端口/路由/ICE 异常 → 201/Location 取证与 /metrics 指标 → 自动重试 + 降级路径
- Graphs 不一致 → FS/DB 源混用 → 统一 DB-only + 配置开关 → 前后端统一映射
- 进程不稳定 → VA 被占用/退出 → 启停脚本与健康探测 → 出错自动重启
- 性能瓶颈 → 并发/大表查询 → 分页与索引、聚合指标 → 首帧/成功率监控
