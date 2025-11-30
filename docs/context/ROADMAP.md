# 路线图总览

- **M0：Spring 版 CP 骨架可用**
  - 目标：`controlplane-spring` 能在 Docker 环境下编译、启动，并通过核心 Python 脚本的最小回归（system.info / subscriptions / sources 列表 / VA runtime）。
  - 验收标准：
    - `cp-spring` 容器健康 (`/api/system/info` 200)；
    - `check_cp_system_info.py`、`check_cp_min_api_once.py`、`check_cp_json_negative.py`、`check_cp_sse_placeholder.py`、`check_cp_sse_watch.py`、`check_cp_sources_watch_sse.py` 全部 PASS 或约定内 SKIP；
    - `/api/va/runtime` 能返回 VA 真实状态。

- **M1：控制与源管理链路对齐 C++ CP**
  - 目标：Spring 版 CP 在 `/api/control/*` 与 `/api/sources*` 上实现与 C++ 版等价的行为（语义上兼容，性能可稍弱），并在 VA/VSM 正常可用时通过大部分 controlplane 脚本。
  - 验收标准：
    - `/api/control/apply_pipeline/remove_pipeline/hotswap/drain/set_engine/pipelines` 端到端跑通与 VA 的交互；
    - `/api/sources:attach|:detach|:enable|:disable` / `/api/sources` 与 VSM 行为一致，脚本不再因为 cp-spring 本身而 FAIL；
    - SSE `/api/subscriptions/{id}/events` / `/api/sources/watch_sse` 在具备下游条件时能持续输出事件。

- **M2：观测、安全与灰度发布完善**
  - 目标：Spring 版 CP 拥有稳定的观测、安全与灰度切换能力，允许与 C++ CP 并行部署并可安全回滚。
  - 验收标准：
    - Micrometer + Prometheus 暴露控制平面关键指标，Grafana 仪表盘覆盖主要视图；
    - Spring Security（或等价机制）保护敏感控制接口；
    - 完成 C++ CP / cp-spring 的灰度切换与回滚演练，有文档化预案。

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| Phase A–B | cp-spring 骨架 + gRPC 通道 | Spring Boot 3.1 + Java 21；Netty gRPC 通道；TLS/mTLS 与 SAN override | TLS 证书/SAN 不匹配 → 对齐 CA & 使用 `overrideAuthority("localhost")` | cp-spring 可在 Docker 启停；`/api/system/info` 200 |
| Phase C | VA/VSM gRPC 客户端封装 | `VideoAnalyzerClient` / `VideoSourceManagerClient`；Resilience4j circuit breaker；合理 deadline | 下游超时导致 HTTP 卡死 → 设置 per-call deadline + 全局异常映射 | VA `Subscribe/Apply/Drain/ListPipelines/QueryRuntime`、VSM `Attach/Update/GetHealth/WatchState` 在健康环境可用 |
| Phase D | REST + SSE 对齐 CP 语义 | `/api/subscriptions`、`/api/sources*`、`/api/control/*`、`/api/va/runtime`；`/api/subscriptions/{id}/events` / `/api/sources/watch_sse` | 与旧 CP 行为差异 → 以 Python 脚本为契约回归；必要时保留小差异并文档化 | 当前所有 `controlplane/test/scripts` 在 VA/VSM 就绪时 PASS 或仅因后端缺失而 SKIP |
| Phase E | 缓存层与一致性 | Caffeine 缓存 `system.info` / sources；必要时引入 Redis；冷启动/异常场景一致性验证 | 缓存陈旧/双写不一致 → 严格 TTL + 写路径显式失效；在异常场景关闭缓存 | `/api/system/info`、`/api/sources` 在缓存开启时无错误，且与 C++ CP 行为一致 |
| Phase F | 安全与观测 | Spring Security / Token 校验；Micrometer 自定义指标；Prometheus/Grafana 仪表盘 | 权限模型不一致 → 先复刻 C++ CP 的 token 行为，再逐步增强 | 对关键接口的 QPS/latency/error-rate 在 Grafana 中可见，安全策略通过测试脚本验证 |
| Phase G | 测试与灰度/回滚 | Spring Boot 单测/集成测试；灰度切换策略；回滚预案 | 灰度中出现行为分裂 → 前后端/Agent 层支持按环境切换目标 CP；统一日志与指标标签 | 至少一套成功的灰度演练记录（包括切换和回滚），并有可复用脚本/文档 |

# 依赖矩阵

- **内部依赖：**
  - `video-analyzer`：`AnalyzerControl` gRPC 服务（订阅/管线/引擎/模型仓库）。
  - `video-source-manager`：`SourceControl` gRPC 服务（源 attach/detach/update/health/watch）。
  - `controlplane/test/scripts`：Python/PowerShell 回归脚本，是 HTTP 语义的事实契约。
  - `db/` + `cv_cp`：MySQL 控制平面配置库，用于 models/pipelines/graphs/train_jobs。

- **外部依赖（库/服务/硬件）：**
  - Spring Boot 3.1.x、Java 21、Maven（Docker 内构建工具链）。
  - gRPC Java（1.77），protobuf（4.33.1）。
  - Resilience4j、Caffeine、Micrometer + Prometheus。
  - Docker 环境（VA/VSM/mysql/minio/pgvector 等 Service 依赖）。
  - GPU 资源（主要由 VA 使用；cp-spring 本身只需 CPU）。

# 风险清单（Top-5）

- **VA/VSM gRPC 不稳定 → HTTP 层频繁 5xx**
  - 触发条件：TLS 配置错误、SAN 不匹配、网络抖动、VA/VSM 重启。
  - 监控信号：`StatusRuntimeException` 日志、Resilience4j 断路器状态、Micrometer error-rate。
  - 预案：为所有下游调用设置合理 deadline；在 cp-spring 中对某些操作（如 sources 列表）提供降级路径或 SKIP 语义。

- **cp-spring 与 C++ CP 行为偏差**
  - 触发条件：JSON 字段名/错误码不一致；缺失某些边缘路由或特殊处理。
  - 监控信号：控制平面脚本 FAIL；前端/Agent 逻辑针对 cp-spring 报错。
  - 预案：以脚本为准进行约束回归；必要时保留兼容层（如 profile/source_id 的映射），并在文档中明确差异。

- **缓存带来的数据陈旧或一致性问题**
  - 触发条件：源状态或 system.info 频繁变动；缓存 TTL 设置过长或失效策略不当。
  - 监控信号：用户报告“列表不刷新”；日志中的 cache miss/hit 比例异常。
  - 预案：将缓存应用限制在只读、非关键路径；写操作后显式失效；异常场景可动态关闭缓存。

- **安全配置与旧 CP 不一致**
  - 触发条件：引入 Spring Security 后未同步 C++ CP 的 token/权限语义。
  - 监控信号：脚本或前端请求被 401/403 拒绝；日志中出现大量认证失败。
  - 预案：先以“兼容旧 CP”模式启用安全（如仅校验已有 token），再逐步增强；为敏感接口添加 feature flag 控制。

- **灰度切换期间前端/Agent 行为分裂**
  - 触发条件：部分请求指向 C++ CP，部分指向 cp-spring，而两者行为尚未完全统一。
  - 监控信号：相同操作在不同会话中结果不一致；日志中出现混合来源的异常。
  - 预案：设计明确的切换策略（基于域名/路径/配置开关）；在灰度期只开放读操作到 cp-spring，写操作仍走 C++ CP；若发现问题，按预案快速回滚流量。 
