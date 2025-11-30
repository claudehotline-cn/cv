# 路线图总览

- **M0：cp-spring 完全接管控制平面**
  - 目标：在 Docker 环境下由 cp-spring 独立承担所有 CP 职责，对前端、Agent 与测试脚本透明，C++ CP 不再承载任何线上流量。
  - 验收标准：
    - 所有 `controlplane/test/scripts/check_cp_*` 在 cp-spring 下通过。
    - web-front 与 agent 仅依赖 `cp-spring:18080`，docker-compose 中不再暴露 C++ CP 端口。
    - `/metrics`、`/api/events/*`、Repo / Train / Agent / `_debug/db` 等接口行为与历史预期兼容。
- **M1：观测、安全与可运维性增强**
  - 目标：在 cp-spring 上构建比 C++ CP 更强的观测、审计和安全能力，支撑长时间稳定运行。
  - 验收标准：
    - Prometheus 中覆盖 HTTP/gRPC/SSE/Repo/Train 等关键指标，Grafana 提供 cp-spring 总览大盘。
    - 关键控制接口支持可配置 Bearer Token 鉴权，并有结构化审计日志。
    - 发生 VA/VSM/DB/Trainer 故障时，能够通过指标与日志快速定位并恢复。
- **M2：长期演进与 C++ CP 彻底下线**
  - 目标：在保持兼容的前提下简化架构、清理遗留依赖，并为后续特性预留空间。
  - 验收标准：
    - docker-compose 与发布文档中删除 C++ CP 作为依赖，仅保留独立“对比环境”（可选）。
    - 所有新特性在 cp-spring 上统一实现，旧 C++ 代码库标记为只读/归档。
    - CONTEXT / ROADMAP / memo 中有完整的迁移与下线记录。

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| Phase A | cp-spring 基础骨架与配置（已完成） | Spring Boot 3.x、AppProperties、Actuator、CI 构建 | 依赖版本漂移 → 锁定 BOM 与 JDK 版本 | `/actuator/health` 稳定 200 |
| Phase B | VA/VSM gRPC 客户端与 Repo/Train 接口（已完成） | Netty gRPC、Resilience4j、Trainer 反向代理 | TLS/地址配置错误 → 统一 env key 并提供明文回退 | gRPC error rate < 1% |
| Phase C | HTTP/SSE API 迁移与兼容层（已完成） | 订阅、源管理、控制、编排、Repo、Train、Agent 代理、`_debug/db`、`/metrics` alias | 行为偏差 → 以 Python 脚本和前端为契约对齐 | 所有 CP 回归脚本通过 |
| Phase D | 观测、安全与审计增强（进行中） | Micrometer 指标、Grafana 看板、Bearer Token、审计日志 | 指标/告警缺失 → 以 C++ CP 指标表为基线补齐 | 关键接口都有 QPS/延迟/错误率曲线 |
| Phase E | 清理 C++ CP 依赖与文档收束（待办） | 更新 docker-compose、部署手册、CONTEXT/ROADMAP | 误删仍被使用的端点 → 全仓搜引用并观察访问日志 | 线上无直接访问 C++ CP 的流量 |

# 依赖矩阵

- 内部依赖：
  - `video-analyzer`（VA）：AnalyzerControl gRPC、Repo/模型转换能力。
  - `video-source-manager`（VSM）：源管理 gRPC 与 RTSP 拉流。
  - `model-trainer`：训练 HTTP + SSE 事件流。
  - MySQL `cv_cp`：pipelines / graphs / models / train_jobs 等配置与状态。
  - `web-frontend`、`agent`：通过 `VITE_CP_BASE_URL` / `AGENT_CP_BASE_URL` 访问 cp-spring。
- 外部依赖（库/服务/硬件）：
  - Spring Boot、Micrometer、Resilience4j、MyBatis-Plus。
  - Prometheus / Grafana、Docker / docker compose。
  - GPU 服务器、RTSP 摄像头与网络。

# 风险清单（Top-5）

- 行为与历史不一致 → 前端或脚本异常 → 日志出现大量 4xx/5xx → 以契约测试（Python 脚本 + UI 冒烟）覆盖所有关键接口，变更前后必跑一轮对比。
- gRPC/Trainer 链路不稳定 → Repo/Train 操作失败 → 指标中 error rate 或重试暴增 → 为 VA/VSM/Trainer 配置超时与重试上限，必要时降级关闭相关功能入口。
- 观测缺口 → 故障仅能通过用户反馈发现 → 无相关指标或告警 → 先为核心路径补齐指标，再在 Grafana 中配置基本告警阈值。
- 配置漂移或环境不一致 → 不同环境行为不一 → 同一接口在 dev/stage/prod 返回差异结构 → 关键配置集中在 env 与 `application-*.yml` 并在 CONTEXT 中记录，定期比对。
- C++ CP 依赖未完全清理 → 某些脚本/工具仍访问旧地址 → 访问日志中出现对 C++ CP 的请求 → 在完全下线前通过日志与全仓 grep 确认引用，必要时为少量遗留调用提供短期兼容跳转。
