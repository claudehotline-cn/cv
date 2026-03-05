# Phase2 SOLID Ports / Adapters 边界说明（简版）

## 目标
在 Phase2 中保持平台层与核心层职责清晰，避免把 HTTP/租户策略耦合进运行时核心。

## 边界划分

### platform/api（`agent-platform-api`）
- 对外 HTTP 路由与协议：请求/响应、状态码、路径契约。
- 认证与授权：`AuthPrincipal`、`get_current_user`、`require_admin`。
- 租户作用域与防越权：例如 cross-tenant 拒绝、tenant membership 校验。
- 运营入口：`/cache/me/stats`、`/admin/tenants/{tenant_id}/cache/invalidate`、`/guardrails/me`。
- 组合根（composition root）：装配路由、服务与基础设施依赖。

### core（`agent-core`）
- 运行时抽象与可复用能力：settings、middleware、ports、adapters。
- 观测与配置基元：`OTEL_ENABLED`、`OTEL_FAIL_MODE` 等开关语义。
- 与具体 Web 框架无关的逻辑：不依赖 FastAPI 路由与 HTTP 细节。

## 协作约束
- platform 依赖 core 的抽象能力，不反向依赖 platform。
- 新增 API 时，先在 platform 层定义 contract test，再最小实现。
- 文档与契约保持同步：runbook 关键接口变更需同步 `docs/production_readiness.md` 与 docs contract 测试。
