# 第二阶段 SOLID 重构（Guardrails + OTel + Semantic Cache）实施计划

> **For Claude：** 必须使用子技能 `superpowers:executing-plans` 按任务逐步执行本计划。

**目标：** 在不破坏现有多租户、审计、异步 Worker 主链路的前提下，构建生产可用且符合 SOLID 的执行管线，落地 Guardrails、OpenTelemetry 可观测性与 Semantic Cache。

**架构：** 采用 Ports & Adapters（六边形）架构：`agent-core` 放应用编排与抽象端口，`agent-platform-api` 放具体适配器实现。API 路由与 Worker 通过依赖注入/组合根调用 orchestrator，不直接耦合具体服务。延续当前 `init_db` 轻量迁移风格及治理/Prompt/Eval 的 contract-test 风格。

**技术栈：** FastAPI、SQLAlchemy Async、PostgreSQL（JSONB + pgvector）、Redis/ARQ、OpenTelemetry OTLP、Vue3 + Pinia + Element Plus。

---

## 任务 1：定义 SOLID 端口与决策模型（不耦合基础设施）

**文件：**
- 新建：`agent-core/agent_core/contracts/guardrails.py`
- 新建：`agent-core/agent_core/contracts/semantic_cache.py`
- 新建：`agent-core/agent_core/contracts/telemetry.py`
- 新建：`agent-core/agent_core/application/models.py`
- 修改：`agent-core/agent_core/__init__.py`
- 测试：`agent-platform-api/test/test_phase2_ports_contract.py`

**步骤：**
1. 先写失败测试（端口与模型可导入、字段存在）。
2. 运行测试确认失败：
   `docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_phase2_ports_contract.py -q`
3. 最小实现：定义 `GuardrailPort`、`SemanticCachePort`、`TelemetryPort` 与 `GuardrailDecision` 等模型。
4. 再跑测试确认通过。
5. 提交。

---

## 任务 2：在 `agent-core` 构建应用 orchestrator（唯一入口）

**文件：**
- 新建：`agent-core/agent_core/application/orchestrator.py`
- 新建：`agent-core/agent_core/application/policy.py`
- 测试：`agent-platform-api/test/test_phase2_orchestrator_contract.py`

**步骤：**
1. 写失败测试：cache miss 时会调用 live executor。
2. 运行测试确认失败。
3. 最小实现 `RequestExecutionOrchestrator.execute()`：
   - pre-input guardrail
   - semantic cache lookup
   - miss 时执行 live executor
   - post-output guardrail
   - 可缓存时写缓存
4. 测试通过。
5. 提交。

---

## 任务 3：补齐 Guardrails/Cache 的 DB 模型与 inline migration（Phase 2 schema）

**文件：**
- 修改：`agent-platform-api/app/models/db_models.py`
- 修改：`agent-platform-api/app/db.py`
- 测试：`agent-platform-api/test/test_phase2_migration_contract.py`

**步骤：**
1. 写失败测试：`init_db()` 后三张表存在。
2. 运行测试确认失败。
3. 最小实现：
   - `tenant_guardrail_policies`
   - `guardrail_events`
   - `semantic_cache_entries`
   - 必要索引（tenant/namespace/model、event_time）
   - pgvector 安全启用（`CREATE EXTENSION IF NOT EXISTS vector`）
4. 测试通过。
5. 提交。

---

## 任务 4：实现基础设施适配器（Guardrails DB、pgvector Cache、OTel Telemetry）

**文件：**
- 新建：`agent-platform-api/app/adapters/guardrails_db.py`
- 新建：`agent-platform-api/app/adapters/cache_pgvector.py`
- 新建：`agent-platform-api/app/adapters/telemetry_otel.py`
- 修改：`agent-core/agent_core/observability.py`
- 修改：`agent-core/agent_core/settings.py`
- 测试：`agent-platform-api/test/test_phase2_adapters_contract.py`

**步骤：**
1. 写失败测试：三个 adapter 可导入。
2. 运行测试确认失败。
3. 最小实现：
   - `DbGuardrailAdapter`：加载租户策略，执行输入/工具/输出校验，记录 guardrail event。
   - `PgVectorSemanticCacheAdapter`：向量检索、阈值命中、TTL、写入与命中计数。
   - `OTelTelemetryAdapter`：封装 span/counter/histogram。
   - `settings.py` 新增 OTel 与 Semantic Cache 配置项（`OTEL_ENABLED` 等）。
4. 测试通过。
5. 提交。

---

## 任务 5：新增 composition root，并在 API 启动注入 orchestrator

**文件：**
- 新建：`agent-platform-api/app/composition_root.py`
- 修改：`agent-platform-api/app/main.py`
- 测试：`agent-platform-api/test/test_phase2_composition_contract.py`

**步骤：**
1. 写失败测试：`main.py` 中存在 `composition_root` 和 `app.state.phase2`。
2. 运行测试确认失败。
3. 最小实现：
   - `Phase2Container`（orchestrator/guardrails/cache/telemetry）
   - `build_phase2_container(...)`
   - 在 lifespan startup 注入 `app.state.phase2`
4. 测试通过。
5. 提交。

---

## 任务 6：在 chat/rag/tasks 路由与 worker 接入 orchestrator

**文件：**
- 修改：`agent-platform-api/app/routes/chat.py`
- 修改：`agent-platform-api/app/routes/rag.py`
- 修改：`agent-platform-api/app/routes/tasks.py`
- 修改：`agent-platform-api/app/worker.py`
- 测试：`agent-platform-api/test/test_phase2_pipeline_hooks_contract.py`

**步骤：**
1. 写失败测试：上述主流程文件包含 orchestrator 调用。
2. 运行测试确认失败。
3. 最小实现：
   - 路由从 `request.app.state.phase2.orchestrator` 调用统一执行。
   - `agent_execute_task` / `agent_resume_task` 走同一 orchestrator 逻辑。
   - 保持既有 quota/concurrency/audit 生命周期不变。
4. 测试通过。
5. 提交。

---

## 任务 7：新增 Guardrails 管理与审计查询 API

**文件：**
- 新建：`agent-platform-api/app/routes/guardrails.py`
- 修改：`agent-platform-api/app/routes/audit.py`
- 修改：`agent-platform-api/app/main.py`
- 测试：`agent-platform-api/test/test_phase2_guardrails_api_contract.py`

**步骤：**
1. 写失败测试：`main.py` 注册 `guardrails.router`。
2. 运行测试确认失败。
3. 最小实现：
   - `GET /guardrails/me`
   - `GET/PUT /admin/tenants/{tenant_id}/guardrails`
   - `GET /audit/guardrails`
4. 测试通过。
5. 提交。

---

## 任务 8：新增 Semantic Cache 管理与统计 API

**文件：**
- 新建：`agent-platform-api/app/routes/cache_admin.py`
- 修改：`agent-platform-api/app/main.py`
- 测试：`agent-platform-api/test/test_phase2_cache_api_contract.py`

**步骤：**
1. 写失败测试：`main.py` 注册 `cache_admin.router`。
2. 运行测试确认失败。
3. 最小实现：
   - `GET /cache/me/stats`
   - `GET /admin/tenants/{tenant_id}/cache/entries`
   - `POST /admin/tenants/{tenant_id}/cache/invalidate`
4. 测试通过。
5. 提交。

---

## 任务 9：前端最小页面与 API 绑定

**文件：**
- 修改：`agent-chat-vue/src/api/client.ts`
- 修改：`agent-chat-vue/src/router.ts`
- 修改：`agent-chat-vue/src/views/settings/SecurityCenterView.vue`
- 新建：`agent-chat-vue/src/views/settings/CacheMetricsView.vue`
- 修改：`agent-chat-vue/src/stores/security.ts`
- 测试：`agent-platform-api/test/test_phase2_frontend_contract.py`

**步骤：**
1. 写失败测试：`router.ts` 存在 `SettingsCacheMetrics` 与 `CacheMetricsView.vue`。
2. 运行测试确认失败。
3. 最小实现：
   - `client.ts` 补 Guardrails/Cache 相关接口。
   - `router.ts` 增加 `/settings/cache-metrics` 子路由。
   - `SecurityCenterView.vue` 增加缓存页快捷入口与 Guardrails 状态卡。
   - 新建 `CacheMetricsView.vue` 展示命中率、延迟收益、失效操作（管理员）。
4. 测试通过。
5. 提交。

---

## 任务 10：OTel 指标与 Trace 断言（验证优先）

**文件：**
- 测试：`agent-platform-api/test/test_phase2_otel_contract.py`
- 修改：`agent-platform-api/app/adapters/telemetry_otel.py`
- 修改：`agent-core/agent_core/observability.py`

**步骤：**
1. 写失败测试：声明并使用以下指标名：
   - `agent_run_duration_ms`
   - `tool_call_duration_ms`
   - `agent_errors_total`
   - `llm_tokens_prompt_total`
   - `llm_tokens_completion_total`
   - `llm_cost_usd_total`
2. 运行测试确认失败。
3. 最小实现：
   - 绑定 API 根 span（`http.request`）和 orchestrator span（`agent.run`）
   - tool/rag 关键段落创建子 span
4. 测试通过。
5. 提交。

---

## 任务 11：容器内端到端契约验证

**文件：**
- 测试：`agent-platform-api/test/test_phase2_end_to_end_contract.py`
- 修改：`scripts/run-agent-tests.sh`

**步骤：**
1. 写失败测试占位并确认失败。
2. 最小实现真实 e2e 断言：
   - policy block 场景返回 blocked 并记录 guardrail event
   - 第二次请求走 cache hit
   - trace id / request id 在审计链路相关联
3. 更新 `scripts/run-agent-tests.sh` 纳入 phase2 子集。
4. 运行并确认通过：
   - `docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_phase2_end_to_end_contract.py -q`
   - `bash scripts/run-agent-tests.sh`
5. 提交。

---

## 任务 12：文档与运维 Runbook

**文件：**
- 修改：`docs/production_readiness.md`
- 新建：`docs/design/phase2_solid_ports_adapters.md`
- 修改：`CLAUDE.md`

**步骤：**
1. 写失败测试：文档包含 `OTEL_ENABLED`、`SEMANTIC_CACHE_SIMILARITY_THRESHOLD`、`tenant_guardrail_policies`。
2. 运行测试确认失败。
3. 最小实现文档内容：
   - 环境变量
   - migration 冒烟检查 SQL
   - 最小仪表盘集合
   - fallback 策略（`OTEL_FAIL_MODE=open`、按租户关闭 guardrails）
4. 测试通过。
5. 提交。

---

## 合并前完整验证清单

1. Phase2 定向测试：

```bash
docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_phase2_* -q
```

期望：全部 PASS。

2. 既有治理/Eval 回归：

```bash
docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_governance_m2_contract.py /workspace/agent-platform-api/test/test_eval_routes_contract.py /workspace/agent-platform-api/test/test_prompt_ab_eval_migration_contract.py -q
```

期望：PASS，且无现有模块回归。

3. 前端构建：

```bash
cd agent-chat-vue && npm run build
```

期望：Vite 构建成功。

4. 冒烟接口：

```bash
curl -fsS http://localhost:18111/health
curl -fsS http://localhost:18111/guardrails/me -H "Authorization: Bearer <token>"
curl -fsS http://localhost:18111/cache/me/stats -H "Authorization: Bearer <token>"
```

期望：健康检查 200，鉴权后接口 200。

---

## 执行纪律说明

- 每个任务执行时使用 `@superpowers:test-driven-development`。
- 任一契约失败时使用 `@superpowers:systematic-debugging`。
- 每个提交只包含一个任务范围。
- 除 Ports/Orchestrator/Adapters 外不引入额外抽象（避免过度设计）。
- 接入 orchestrator 时必须保留现有 auth/quota/governance 语义。