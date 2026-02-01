# RAG Datasets & Benchmarks + Sidebar Navigation Plan

本文档描述在当前 Agent 平台中，将 RAG 模块补齐为“可评测、可运维、可审计”的完整功能闭环的实现方案。

目标约束（已确认）
- 前端只调用 `agent-api`（不直连 `rag-service`）
- 写/执行操作：admin-only
- Dataset：每个 Knowledge Base 独立一套（必须绑定 `kb_id`）
- Benchmarks：支持 Vector + Graph 两种检索模式
- 审计不新增 RAG 审计页面，复用平台现有 `/audit` 模块
- 导航方式：RAG 模块的页面通过“RAG 模块 sidebar”导航；RAG sidebar 需包含一个返回全局 Dashboard 的入口

当前仓库现实
- 全局 `#app` 在 `agent-chat-vue/src/App.vue` 内设置了 `overflow: hidden`，因此每个页面必须自己提供可滚动区域。
- 平台全局 sidebar：`agent-chat-vue/src/components/layout/AppSidebar.vue`（目前用于 Dashboard、Audit 等页面）
- RAG 模块入口页：`/finance-docs`（`agent-chat-vue/src/views/KnowledgeBase.vue`），页面内自带 sidebar
- RAG 检索评测页：`/rag-eval`（`agent-chat-vue/src/views/RagEval.vue`）
- 文档分块编辑页：`/document-editor`（`agent-chat-vue/src/views/DocumentEditor.vue`）
- 平台审计页：`/audit`（`agent-chat-vue/src/views/AuditView.vue`）

## 1. 信息架构（IA）与导航

### 1.1 平台全局 sidebar（AppSidebar）

原则：全局 sidebar 只负责“进入 RAG 模块”，不承载 RAG 子页面导航。

- 保留：`Knowledge Base` -> `/finance-docs`（进入 RAG 模块）
- 删除：全局 `RAG Evaluation` 入口（避免入口分裂）

涉及文件
- `agent-chat-vue/src/components/layout/AppSidebar.vue`

### 1.2 RAG 模块 sidebar

原则：RAG 模块内部页面导航统一放在“RAG 模块 sidebar”中（类似 Chat 模块有自己的 sidebar），并提供返回全局 Dashboard 的入口。

菜单顺序（已确认 A）：
1. Dashboard -> `/`
2. Knowledge Base -> `/finance-docs`
3. Retrieval Lab -> `/rag-eval?kbId=<selectedKbId>`
4. Datasets -> `/rag/datasets?kbId=<selectedKbId>`
5. Benchmarks -> `/rag/benchmarks?kbId=<selectedKbId>`
6. Audit (RAG) -> `/audit?agent=rag`

实现建议：抽组件复用
- 新增：`agent-chat-vue/src/components/rag/RagModuleSidebarNav.vue`
- 在以下页面的 sidebar 顶部复用：
  - `agent-chat-vue/src/views/KnowledgeBase.vue`
  - `agent-chat-vue/src/views/RagEval.vue`
  - `agent-chat-vue/src/views/DocumentEditor.vue`

## 2. 后端：rag-service 数据模型（MySQL）

落库目标
- Dataset 与 Case 能持久化、可导入导出
- Benchmark Run 能异步执行（ARQ job），并落库保存 run 指标与逐 case 结果

存储位置
- 建议放在 `rag-service` 的 MySQL（当前已用于存储 KB 与 Document 元数据）

### 2.1 新增表（建议字段）

#### 2.1.1 rag_eval_datasets
- `id` (PK, int)
- `knowledge_base_id` (FK to rag_knowledge_bases.id, NOT NULL)
- `name` (string)
- `description` (text, nullable)
- `created_by` (string, user_id)
- `created_at`, `updated_at`

#### 2.1.2 rag_eval_cases
- `id` (PK)
- `dataset_id` (FK to rag_eval_datasets.id)
- `query` (text)
- `expected_sources` (text/json；用于自动指标匹配，建议为 list[str])
- `notes` (text, nullable)
- `tags` (text/json, nullable)
- `created_at`, `updated_at`

#### 2.1.3 rag_benchmark_runs
- `id` (PK)
- `knowledge_base_id` (NOT NULL)
- `dataset_id` (NOT NULL)
- `mode` (enum: vector|graph)
- `top_k` (int)
- `status` (queued|running|succeeded|failed)
- `created_by` (string)
- `request_id` (string UUID，用于审计串联)
- `metrics` (json/text：precision@k/mrr@k/ndcg@k 等)
- `created_at`, `started_at`, `ended_at`
- `error_message` (text)

#### 2.1.4 rag_benchmark_case_results
- `id` (PK)
- `run_id` (FK)
- `case_id` (FK)
- `hit_rank` (int nullable；第一个命中的 rank)
- `mrr` (float)
- `ndcg` (float)
- `retrieved` (json/text；保存 top_k 结果用于 UI 展示/导出)
- `created_at`

涉及文件
- `rag_service/rag_service/models.py`
- `rag_service/rag_service/database.py`（如需 best-effort migration；当前 repo 无 Alembic）

## 3. 后端：rag-service API 设计

约束
- 这些 API 都由 `agent-api` 网关代理；前端不直连
- 写/执行操作由网关限制 admin-only

### 3.1 Dataset API（按 KB 隔离）
- `GET  /api/knowledge-bases/{kb_id}/eval/datasets`
- `POST /api/knowledge-bases/{kb_id}/eval/datasets`
- `GET  /api/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}`
- `PUT  /api/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}`
- `DELETE /api/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}`

Cases
- `GET  /api/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/cases`
- `POST /api/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/cases`
- `PUT  /api/eval/cases/{case_id}`
- `DELETE /api/eval/cases/{case_id}`

Import/Export
- `POST /api/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/import`
- `GET  /api/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/export`

### 3.2 Benchmarks API（异步执行）
- `POST /api/knowledge-bases/{kb_id}/eval/benchmarks/runs`（创建 run）
- `POST /api/knowledge-bases/{kb_id}/eval/benchmarks/runs/{run_id}/execute`（enqueue ARQ job）
- `GET  /api/knowledge-bases/{kb_id}/eval/benchmarks/runs`（列表）
- `GET  /api/knowledge-bases/{kb_id}/eval/benchmarks/runs/{run_id}`（详情+汇总指标）
- `GET  /api/knowledge-bases/{kb_id}/eval/benchmarks/runs/{run_id}/results`（逐 case 结果）
- `GET  /api/knowledge-bases/{kb_id}/eval/benchmarks/runs/{run_id}/export`

### 3.3 Benchmarks 执行逻辑（ARQ job）
run 执行逐 case 调用：
- vector：`rag_retriever.retrieve(query, kb_id, top_k=top_k)`
- graph：`graph_retriever.retrieve(query, kb_id, depth=2)`

自动指标（基于 expected_sources 与结果的 `metadata.source` 匹配）：
- hit@k（是否命中）
- MRR@k（第一个命中 rank 的倒数）
- nDCG@k（初期可按二值相关性计算）

Graph 模式注意点
- 现状 graph_retrieve 在 API 里返回 `document_id=0`（无法可靠跳转 DocumentEditor）
- 因此 Benchmarks 的 ground truth 匹配以 `metadata.source` 为准
- 若要支持跳转，需要额外实现 `source -> Document.id` 的反查映射（后续增强项）

## 4. agent-api 网关（/rag）

原则
- 前端只调用 `agent-api`
- 网关负责：权限（admin-only 写/执行）、审计事件 emit、透传 `X-Request-Id`

需要新增/扩展的网关路由
- 将 rag-service 的 `/api/knowledge-bases/{kb_id}/eval/...`、`/api/eval/...` 对应映射到 `agent-api` 的 `/rag/...`

审计串联
- 网关继续 emit：`run_started` / `tool_call_requested` / `job_queued` / `run_finished` / `run_failed`
- 对 ARQ job：通过透传 `X-Request-Id` 并设置 `_job_id=request_id`，使 run 与 job 生命周期可在 `/audit` 中串起来

涉及文件
- `agent-platform-api/app/routes/rag.py`

## 5. 前端：RAG 模块页面

新增路由
- `/rag/datasets` -> `agent-chat-vue/src/views/rag/RagDatasets.vue`
- `/rag/benchmarks` -> `agent-chat-vue/src/views/rag/RagBenchmarks.vue`

涉及文件
- `agent-chat-vue/src/router.ts`

### 5.1 RagDatasets 页面
功能（admin-only 写）：
- Dataset 列表：创建/删除/编辑
- Dataset 详情：Case 列表 CRUD
- Import/Export

### 5.2 RagBenchmarks 页面
功能（admin-only 执行）：
- 创建 run（选择 dataset + mode + top_k）
- 执行 run（enqueue）
- 列表与详情：展示汇总指标 + per-case 结果
- 导出报告

### 5.3 统一 RAG sidebar 导航
实现：`RagModuleSidebarNav.vue` 作为“RAG 模块 sidebar 菜单块”，嵌入到
- `KnowledgeBase.vue` 的 sidebar 顶部
- `RagEval.vue` 的 sidebar 顶部（满足“导航在 sidebar”）
- `DocumentEditor.vue` 的左侧栏顶部

## 6. 审计：归到平台 Audit 模块

原则
- 不在 KnowledgeBase/RAG 页面新增审计页
- RAG sidebar 提供“跳转到审计”的入口（带过滤参数）

需要增强 Audit 页（便于深链过滤）
- `agent-chat-vue/src/views/AuditView.vue`
  - 支持从 URL query 初始化筛选条件：`agent=rag`、`q=<request_id>` 等
  - agent 下拉 options 增加 `rag`（当前 options 来源于 `listAgents()`，不会包含 rag）

## 7. 里程碑（建议实现顺序）

1) 后端落库与 API（rag-service）
- models + routes + benchmark ARQ job
2) agent-api 网关代理与权限
3) 前端：新增 `RagDatasets.vue`、`RagBenchmarks.vue` + 路由
4) 前端：抽 `RagModuleSidebarNav.vue` 并在 RAG 相关页面复用
5) 前端：增强 `AuditView.vue` 支持 `agent=rag` 深链过滤
6) 端到端验收：datasets -> run -> audit trace
