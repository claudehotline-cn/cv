## controlplane Spring Boot 重写 WBS（按阶段）

### 1. 范围澄清与契约梳理

- 1.1 明确重写目标：以 Spring Boot 3.x + Java 21 彻底替换现有 C++ controlplane，可平滑接管前端与 VA/VSM 的全部控制平面流量。
- 1.2 梳理现有 HTTP/SSE/gRPC 契约：以 `docs/design/控制平面HTTP与gRPC接口说明.md` 与 `controlplane/test/scripts/*.py` 为主，整理出路由列表、请求/响应 JSON 结构、错误码与 SSE 事件格式。
- 1.3 确定兼容边界：哪些接口必须 100% 行为兼容（如 `/api/subscriptions`、`/api/orch/*`、`/api/sources*`），哪些可以在 Spring 版本中调整或废弃。
- 1.4 设计总体架构：Controller → 领域 Service → 基础设施（gRPC/DB/缓存）分层，保持与现有 CP 职责对应，同时预留未来扩展空间。

### 2. Spring Boot 项目骨架与基础设施

- 2.1 选定构建工具（Maven/Gradle）并按 Spring Boot 官方教程创建最小可运行的 Web 应用骨架（`ControlPlaneApplication`、基本 `/ping` 接口）。
- 2.2 规划包结构：`config`、`web`、`domain`、`grpc`、`infrastructure`、`sse`、`metrics` 等，确保与现有 C++ 模块（config/db/grpc_clients/http_server/watch_adapter/metrics 等）一一对应。
- 2.3 迁移配置体系：将 `controlplane/config/app.yaml` 映射为 `application.yml` 与若干 `@ConfigurationProperties` 类（服务端口、VA/VSM 目标、DB、缓存、TLS 等）。
- 2.4 搭建基础运行环境：启用 actuator 健康检查、统一日志格式、基础全局异常处理框架，为后续业务功能提供稳定底座。

### 3. gRPC 客户端与下游集成层

- 3.1 梳理 VA/VSM gRPC 接口：从现有 proto 与 `grpc_clients.hpp/cpp` 中提取调用列表（AnalyzerControl、SourceControl 等）及当前参数/错误语义。
- 3.2 实现 gRPC 通道管理：在 Spring 中统一创建 `ManagedChannel`，配置 TLS/mTLS、连接池、超时与最大并发等参数。
- 3.3 封装领域友好的 gRPC 客户端：定义 `VideoAnalyzerClient`、`VideoSourceManagerClient` 等 Bean，将低层 stub 调用隐藏在适配层。
- 3.4 集成熔断与重试：使用 resilience4j 或 Spring Cloud CircuitBreaker 复刻 C++ `circuit_breaker` 行为，输出下游可观测指标。

### 4. REST API 与 SSE 接口迁移

- 4.1 迁移核心 REST API：根据现有 CP 实现和测试脚本，逐个在 Spring 中实现 `/api/subscriptions*`、`/api/system/info`、`/api/sources*`、`/api/control/*`、`/api/orch/*` 等路由。
- 4.2 设计请求/响应 DTO：对照现有 JSON 结构，定义清晰的入参/出参模型，并在 Controller 层保持与旧版接口兼容。
- 4.3 构建统一错误处理与状态码映射：从 gRPC/内部异常映射到稳定的 HTTP 错误语义，复用 `控制面错误码与语义.md` 中已有约定。
- 4.4 实现 SSE 事件流：用 Spring 的 SSE 能力（`SseEmitter` 或 WebFlux）重建 `/api/subscriptions/:id/events` 等 SSE 通道，与 VA Watch 流对接，维护连接数与资源清理。

### 5. 存储、缓存与配置中心迁移

- 5.1 分析 C++ `db.hpp/store.hpp/cache.hpp` 中的存储模型：识别目前依赖的 MySQL/MySQLX 表结构与内存缓存模式。
- 5.2 设计 Spring 侧数据访问层：选择 Spring Data（JPA/JDBC）或 MyBatis，并建立 Repository 接口与实体映射。
- 5.3 替换本地缓存逻辑：使用 Caffeine 或 Redis 实现 `CacheService`，覆盖 system.info 聚合缓存、源状态缓存等场景。
- 5.4 处理配置与元数据管理：规划后续将部分配置迁移到 DB/配置中心的路径，同时保证当前 `app.yaml` 兼容。

### 6. 安全、观测与运维能力

- 6.1 集成 Spring Security（可选）：根据当前 CP 安全方案，为敏感接口引入 Token/JWT/mTLS 校验，并保留调试/回滚开关。
- 6.2 重建指标体系：使用 Micrometer 将 C++ `metrics` 中的关键指标迁移到 Spring，包括请求次数/时延、下游错误统计、SSE 连接数等。
- 6.3 对接 Prometheus/Grafana：暴露 `/actuator/prometheus`，复用或扩展 `docs/examples/grafana_controlplane.md` 中控制平面仪表板。
- 6.4 完善日志与审计：在关键控制操作、编排变更、源增删启停流程中输出结构化审计日志，便于问题回溯。

### 7. 测试、灰度发布与回滚策略

- 7.1 单元与集成测试：围绕领域服务、gRPC 客户端、REST/SSE 接口编写 Spring Boot Test，保证核心路径的回归能力。
- 7.2 复用现有 Python 测试脚本：对新 Spring CP 使用 `controlplane/test/scripts` 下既有用例跑通主要场景，验证行为兼容性。
- 7.3 灰度发布方案：规划“C++ CP 与 Spring CP 并行运行”的阶段，按路由或流量比例切换前端/Agent/VA 调用目标。
- 7.4 回滚预案：定义在 Spring CP 出现问题时快速切回 C++ CP 的操作步骤与配置开关，确保线上风险可控。
