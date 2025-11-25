## controlplane Spring Boot 重写任务清单

### Phase A：范围确认与契约整理

- TA1 整理现有 CP HTTP/SSE 接口：基于 `docs/design/控制平面HTTP与gRPC接口说明.md` 与 `controlplane/test/scripts/*.py`，列出所有现有路由、方法、请求/响应 JSON 示例及主要错误码。
- TA2 梳理现有 gRPC 接口：从 VA/VSM proto 与 `grpc_clients.hpp/cpp` 中整理各服务方法、入参/出参及异常语义，并标注哪些是 Spring 重写必须覆盖的。
- TA3 输出《controlplane Spring 重写边界说明》：明确必须 100% 兼容的接口清单、可以调整/废弃的接口以及不纳入本轮重写的内容。

### Phase B：Spring Boot 项目骨架搭建

- TB1 选择 Maven/Gradle 并创建 `controlplane-spring` 子项目，确保使用 Spring Boot 3.x 与 Java 21，`mvn spring-boot:run` 或等价命令可正常启动。
- TB2 规划并创建基础包结构（`config/web/domain/grpc/infrastructure/sse/metrics`），建立 `ControlPlaneApplication` 与一个简单的 `/ping` 健康接口。
- TB3 迁移 `config/app.yaml` 到 `application.yml`，实现 `AppProperties` 等配置类，包含 VA/VSM 地址、端口、DB/缓存、TLS 等关键信息。
- TB4 接入 Spring Boot Actuator，开放 `/actuator/health` 与基本 info 端点，作为后续测试与监控的基础。

### Phase C：gRPC 客户端与下游集成

- TC1 在 Spring 项目中集成 gRPC 依赖（`grpc-java` + `netty` 或对应 starter），配置 TLS/mTLS 与基础超时参数。
- TC2 实现 `GrpcChannelConfig`，统一创建 VA/VSM 的 `ManagedChannel`，支持连接复用和优雅关闭。
- TC3 编写 `VideoAnalyzerClient` 与 `VideoSourceManagerClient` 封装类，提供面向领域的调用方法，而不是直接暴露 gRPC stub。
- TC4 引入 resilience4j/Spring Cloud CircuitBreaker，为关键下游调用增加超时、重试、熔断与错误统计，并验证与现有 `circuit_breaker` 行为相符。

### Phase D：REST API 与 SSE 实现

- TD1 基于任务 TA1 的接口清单，在 Spring 中实现 `/api/subscriptions`（POST/GET/DELETE）与 `/api/system/info`，确保 JSON 结构和状态码与现有 CP 一致。
- TD2 完成 `/api/sources`（列表、enable/disable、watch 占位）与 `/api/control/*`、`/api/orch/*` 等核心控制与编排接口，实现 Controller → Service → gRPC 客户端的完整调用链。
- TD3 设计并实现统一异常处理（`@ControllerAdvice`）：将内部异常与 gRPC 错误映射为标准化的 HTTP 错误响应结构，覆盖常见错误码（400/404/409/500/503 等）。
- TD4 实现 SSE 相关接口（如 `/api/subscriptions/:id/events`）：采用 `SseEmitter` 或 WebFlux，将 VA Watch 流式事件桥接到 HTTP SSE，处理心跳、断线重连与连接上限控制。

### Phase E：数据访问、缓存与配置

- TE1 分析 C++ `db.hpp/store.hpp/cache.hpp` 与 `db/` 下 SQL，确定 controlplane 依赖的表结构和查询模式。
- TE2 在 Spring 中设计 Entity/DTO/Repository，选择 Spring Data JDBC/JPA 或 MyBatis，实现当前 CP 功能所需的最小读写路径。
- TE3 使用 Caffeine 或 Redis 重建 CP 内部缓存层（如 system.info 聚合缓存、源状态缓存），提供统一的 `CacheService` 接口。
- TE4 验证 Spring 版本下的 DB + 缓存行为与 C++ 版本一致（在正常/异常/冷启动场景下），确保不会引入新的一致性问题。

### Phase F：安全、观测与运维支持

- TF1 根据现有 CP 安全策略，评估并落实 Spring Security 集成方案（如 API Token/JWT/mTLS），对敏感控制接口增加认证与权限校验。
- TF2 基于 Micrometer 定义并实现控制平面关键指标：HTTP 请求 QPS/延迟、gRPC 下游成功率与错误类别、SSE 连接数与事件速率等。
- TF3 对接 Prometheus/Grafana：更新或新增控制平面仪表板，覆盖主要流量、错误与资源使用视图，为后续运维调优提供数据基础。
- TF4 设计并实现审计日志：在编排变更、源 attach/detach、启停、版本切换等操作中记录结构化审计信息，方便问题追踪与合规审计。

### Phase G：测试策略、灰度切换与回滚

- TG1 为主要领域服务、gRPC 客户端与 REST/SSE Controller 编写 Spring Boot 单元与集成测试，覆盖成功链路及关键异常路径。
- TG2 使用 `controlplane/test/scripts` 下的现有 Python 脚本对 Spring 版本 CP 进行端到端回归，记录兼容性差异并逐项修复或确认。
- TG3 设计 C++ CP 与 Spring CP 并行部署方案：包括端口/域名规划、前端与 Agent 侧的目标切换策略、灰度流量分配方式。
- TG4 制定回滚预案与操作手册：明确在 Spring CP 发生故障时的快速切回步骤（包括配置、流量和数据层面），并在测试环境演练。
