# RAG 对接方案：前端页面 + Agent Tool 共用（agent-api 网关 + 审计 + 系统 KB）

## 背景
目标是让 `rag-service` 同时服务两类调用方：
1) 前端 `agent-chat-vue` 的两个 RAG 页面（KnowledgeBase / DocumentEditor）
2) 未来将 RAG 封装成 agent 的 tool（由 agent 执行调用）

同时满足：
- 前端只调用 `agent-api`（不直连 rag-service）
- “系统级 KB”所有用户可读，写操作仅管理员（A）
- DocumentEditor 的 cleaning rules 必须真实生效（影响入库 chunk 与向量）
- 后台可新增 KB（动态 KB 列表）
- 后续 rag 相关动作要接入审计模块（与现有审计链路一致、可落库）

## 现状
### 前端（agent-chat-vue）
- 路由：
  - `/finance-docs` -> `agent-chat-vue/src/views/KnowledgeBase.vue`
  - `/document-editor` -> `agent-chat-vue/src/views/DocumentEditor.vue`
- 两页当前均为 mock UI，无真实 API 调用。
- Vite 代理：仅代理 `/api` 到 `agent-api:8000`，并 rewrite 去掉 `/api`（见 `agent-chat-vue/vite.config.ts`）。

### rag-service
- 现有 API 前缀：`/api/*`（FastAPI）。
- 任务队列：ARQ + Redis（已启用 `RAG_QUEUE_NAME=rag:queue`，避免与其他 worker 冲突）。
- Embedding：Ollama（`bge-m3:567m`，1024 维）。
- LLM/VLM：vLLM OpenAI-compatible（`RAG_VLLM_BASE_URL=http://vllm:8000/v1`）。
- KB 模型：MySQL 表 `rag_knowledge_bases`，`name` 全局唯一且无 owner 字段 -> 天然偏系统级 KB。

### agent-api
- 统一入口（前端只调 `/api`）。
- 现有审计链路：Redis Stream `audit.events` -> 落库到 Postgres（要求 request_id/span_id 可解析为 UUID）。

## 总体架构（强约束）
- UI（前端） -> agent-api（鉴权/权限/审计/限流/转发） -> rag-service（存储/检索/任务执行）
- Tool（agent 调用） -> agent-api（同一套鉴权/审计） -> rag-service

禁止浏览器直连 rag-service（避免绕过权限与审计）。

## 临时鉴权方案（开发期）
使用两档角色：
- Header:
  - `X-User-Id: dev_user_001`
  - `X-User-Role: admin|user`
- 前端先硬编码（方案 1），后续替换为真实登录态/JWT/cookie。
- agent-api 以这两个 header 作为用户上下文来源。

权限规则（系统 KB，A）：
- Read: admin/user 都可读
- Write: 仅 `X-User-Role=admin` 可执行写操作

## 审计接入（与现有落库兼容）
现有审计落库要求：
- `request_id` / `span_id` 能被解析为 UUID
- job 生命周期事件使用 `job_*` 可派生 phase spans（现有落库服务已支持）

约定：
- agent-api 为每个“写操作/长任务”生成 `request_id = uuid4()`（若未来 tool 调用传入 `X-Request-Id` 则沿用）
- agent-api 发审计事件：
  - `job_queued`（入队成功）
  - `job_progress`（可选，多次）
  - `job_completed` / `job_failed`（终态）
- rag-service enqueue ARQ job 时使用 `_job_id=request_id`（ARQ 支持），确保 rag-worker 的执行可以沿用同一个 UUID 作为 request_id 贯穿事件与落库

payload 建议包含：
- `action`: `kb_create|kb_update|doc_upload|rebuild_vectors|build_graph|preview_chunks|doc_reindex`
- `kb_id`, `doc_id`
- `user_id`（来自 `X-User-Id`）
- `queue`: `rag:queue`
- `result`/`error`（终态）

## agent-api：RAG 网关/BFF（对外 API）
前端 baseUrl 是 `/api`，且会 rewrite 掉 `/api`，因此前端发起路径可写为：
- `GET /rag/knowledge-bases`（实际到 agent-api 的 `/rag/...`）

建议 agent-api 暴露前缀：`/rag`（对 UI）：
- `GET    /rag/knowledge-bases`（所有用户可读）
- `POST   /rag/knowledge-bases`（admin-only）
- `GET    /rag/knowledge-bases/{kb_id}`（可读）
- `PUT    /rag/knowledge-bases/{kb_id}`（admin-only，更新 chunk/rules）
- `DELETE /rag/knowledge-bases/{kb_id}`（admin-only，软删除）

- `GET    /rag/knowledge-bases/{kb_id}/documents`（可读）
- `POST   /rag/knowledge-bases/{kb_id}/documents/upload`（admin-only，multipart）
- `POST   /rag/knowledge-bases/{kb_id}/documents/import-url`（admin-only，可选）

- `POST   /rag/knowledge-bases/{kb_id}/rebuild-vectors`（admin-only，长任务）
- `POST   /rag/knowledge-bases/{kb_id}/build-graph`（admin-only，长任务）

- `GET    /rag/knowledge-bases/{kb_id}/documents/{doc_id}/chunks`（可读；后端需补）
- `POST   /rag/knowledge-bases/{kb_id}/documents/{doc_id}/preview-chunks`（admin-only；后端需补）
- `POST   /rag/knowledge-bases/{kb_id}/documents/{doc_id}/reindex`（admin-only；后续增强）

agent-api 到 rag-service 的转发：
- 目标 base：`http://rag-service:8200/api`
- 透传 query/body/multipart/SSE（如需要）

安全/审计：
- 所有写请求：agent-api 生成 request_id 并写审计；并将 request_id 透传给 rag-service（header `X-Request-Id` 或 query）
- 所有写请求：校验 `X-User-Role=admin`，否则 403

## rag-service：为 cleaning rules 生效做的最小改造
### 1) KB 配置持久化
- 在 MySQL `rag_knowledge_bases` 增加：
  - `cleaning_rules`（JSON/TEXT）
  - （可选）`chunking_strategy`（JSON/TEXT）；不需要可省略
- 扩展 rag-service KB API：
  - `POST /api/knowledge-bases` 支持传入 `cleaning_rules`
  - `PUT  /api/knowledge-bases/{kb_id}` 支持更新：
    - `chunk_size`, `chunk_overlap`, `cleaning_rules`

### 2) ingestion pipeline 应用规则
在 rag-worker 的 `process_document(...)`（`rag_service/rag_service/services/ingestion.py`）：
- document_loader.load -> content
- apply_cleaning_rules(content, kb.cleaning_rules)
- chunker（使用 kb.chunk_size/chunk_overlap）
- embed -> 写 `rag_vectors`

cleaning rules 建议（确定性、可复现）：
- removeWhitespace:
  - 启用：压缩多空行/多空格、trim（可复用 `DocumentChunker._preprocess`）
- stripHtml:
  - 移除 HTML 标签 + `html.unescape`
- fixEncoding:
  - `unicodedata.normalize("NFKC")` + 清理 NBSP/zero-width/控制符
- consolidateShortParagraphs:
  - 合并过短段落到邻近段落（固定阈值，避免随机性）

多模态内容（audio transcript / image description）至少应用 removeWhitespace + fixEncoding。

### 3) Preview（强烈建议）
- `POST /api/knowledge-bases/{kb_id}/documents/{doc_id}/preview-chunks`
  - 输入：临时 cleaning rules + chunk_size/overlap（不落库）
  - 输出：前 N 个 chunk（内容截断）+ 统计（chunk_count/avg_len）
  - 不写 pgvector、不做 embedding（快速预览）

## rag-service：为 DocumentEditor 补齐的只读 chunk API
- `GET /api/knowledge-bases/{kb_id}/documents/{doc_id}/chunks?offset&limit&include_parents=1`
  - 数据源：pgvector `rag_vectors`
  - 返回字段建议：
    - `id`, `chunk_index`, `content`, `is_parent`, `parent_id`, `metadata`, `created_at`
    - `tokens_estimate`（前端展示用，简单估算即可）

注意：不做“手工编辑 chunk 文本”，避免引入 canonical chunk 存储与版本管理复杂度。

## 前端对接（agent-chat-vue 两页）
### KnowledgeBase.vue（/finance-docs）
- 用 `/rag/knowledge-bases` 动态渲染 Collections（后台可新增 KB）
- 选择 kb 后，用 `/rag/knowledge-bases/{kb_id}/documents` 填充表格（替换 mock）
- admin-only 显示：
  - 新建 KB
  - 上传文档
  - rebuild vectors / build graph
- 表格行点击跳转 DocumentEditor 时携带 `kbId/docId`（query 或 params）

### DocumentEditor.vue（/document-editor）
- 从 route 获取 `kbId/docId`
- 加载：
  - KB 配置（chunk_size/overlap + cleaning_rules）
  - chunks 分页列表
- 右侧规则面板：
  - Preview -> preview-chunks（admin-only）
  - Save Changes -> `PUT /rag/knowledge-bases/{kb_id}`（admin-only）
  - Regenerate All -> `POST /rag/knowledge-bases/{kb_id}/rebuild-vectors`（admin-only）
- 非 admin 用户：仅可查看 chunks/config，按钮禁用并提示权限不足

### 前端临时身份（写死）
- axios 默认头：`X-User-Id=dev_user_001`，`X-User-Role=user|admin`（开发时手工切换）

## 未来：RAG 封装为 agent tool 的兼容性
- tool 仍调用 agent-api（不要直连 rag-service）
- tool 调用时建议传入：
  - `X-Request-Id = 当前 agent run 的 request_id (UUID)`
  - `X-User-Id/X-User-Role`（跟随 agent-api 用户上下文）
- 这样 tool 调用产生的 rag job 事件可以挂到同一个审计树下，天然可追踪。

## 未来：用户自建 KB 的扩展路径
当前 schema 不含 owner，且 `KnowledgeBase.name` 全局唯一。
扩展建议（后续再做）：
- 增加 `scope`（system|user|org）与 `owner_id`
- 将唯一约束从 `name` 改为复合唯一（例如 `(scope, owner_id, name)`）
- 现有 KB 迁移为 `scope=system`

agent-api 网关层无需推翻，只需在权限判断时加入 scope/owner。

## 实施顺序（建议）
1) agent-api：新增 `/rag` 网关 + 临时 header 鉴权 + admin-only 写权限 + 写操作审计
2) rag-service：KB update 支持 chunk_size/overlap + cleaning_rules（落库）
3) rag-service：ingestion 应用 cleaning_rules（真正生效）
4) rag-service：补 chunks 列表接口 + preview-chunks
5) 前端两页替换 mock，接入 `/rag/*`，并实现 admin-only UI
6) 增强：doc reindex（可选）、任务进度 SSE（可选）

## 测试/验收清单
- user（`X-User-Role=user`）：
  - 能列 KB、能看 docs/chunks
  - 写操作一律 403
- admin：
  - 能创建 KB、上传文档、保存规则、preview、rebuild、build-graph
- cleaning rules 生效验证：
  - 同一文档在不同 cleaning_rules 下，preview 的 chunk 内容/数量变化
  - rebuild 后检索命中内容与清洗后文本一致
- 审计：
  - 写操作对应的 request_id/span_id 均为 UUID
  - job_* 事件可在审计 UI 中检索到（按 request_id）
