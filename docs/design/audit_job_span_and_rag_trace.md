# 审计追踪树：异步 Job 上树 + 独立 RAG 服务上树（物理挂载版）

## 背景
当前平台的审计链路分两层概念：

- **业务 Run（request_id）**：一次业务触发的执行实例，用于审计表的主键/外键聚合（`agent_runs.request_id` ← `audit_events.request_id`）。
- **追踪 Span（span_id / parent_span_id）**：用于构建 Timeline 树的拓扑（`agent_spans.span_id` / `agent_spans.parent_span_id`）。

其中：
- LangChain/LangGraph 自动产生的链路节点使用 **LangChain 原生 `run_id`** 作为 `span_id`；
- LangGraph 的 node 函数没有原生 `run_id`，目前通过 `@node_wrapper` **手动生成 `span_id`**，并写入 `metadata["span_id"]` 来让该 node 内部的 LLM/Tool 调用正确挂到 node span 下。

需求：
1) 异步任务（ARQ job）希望在 Timeline 树中作为一个“顶层节点”出现，并能看到 job 的生命周期事件（queued/started/progress/end…）。
2) RAG 为独立服务，RAG 内部阶段（retrieve/rerank/generate…）也希望出现在同一棵树里，且挂在触发它的上游节点下。
3) **物理挂载**：数据库中的 `agent_spans.parent_span_id` 真实体现调用层级（不是查询时虚拟拼树）。
4) 为避免与 DeepAgent 内部工具名 `task` 混淆，新增顶层节点的 `span_type` 使用 **`job`**（不使用 `task`）。


## 目标与非目标
### 目标
- 异步任务（job）在 Timeline 树中呈现：`job -> agent_root_chain -> ...`
- job 生命周期事件可审计落库并可检索
- 独立 RAG 服务产生的 spans 可以挂入同一棵树
- tracing 仍然以 LangChain 原生 `run_id` 为主，不篡改其生成逻辑
- 允许事件乱序到达（Redis Stream + 多服务并发），仍能最终拼出正确父子关系

### 非目标
- 不在本文中强制定义前端 UI 的全部展示细节（只给出必要字段/约定）
- 不在本文中规定 RAG 的具体业务协议（只约定 trace/audit context 透传）


## 术语
- **request_id**：业务 Run ID（审计聚合 FK）
- **job_id**：异步任务 ID（即 `tasks.id`）
- **job_span**：异步任务在追踪树中的顶层 span（`span_type="job"`）
- **root_chain_span**：一次 agent 执行的根 chain span（LangChain 原生 `run_id`，通常 DB 中最顶层的 chain）
- **parent_span_id**：树结构父指针


## ID 约定（强约束）
### 业务 Run（request_id）
- **异步**：`request_id == job_id == task_id`（UUID）
  - 解释：一个 async job 对应一个业务执行实例，最稳定、最易聚合。
- **同步**：`request_id` 为“用户发送消息触发执行”的 UUID（与 LangChain `run_id` 不同）。

### 追踪 Span（span_id）
- LangChain 自动节点（chain/tool/llm）：`span_id = LangChain 原生 run_id`
- LangGraph node：`span_id = @node_wrapper 手动 uuid4()`
- job 顶层节点：`span_id = job_id`（UUID，**手动**）
- RAG 服务内部节点：`span_id = rag 服务手动 uuid4()`

> 重要：**`request_id`（业务）与 `span_id`（追踪）解耦**。任何时候不要用 LangChain `run_id` 当业务 FK。


## 事件 Envelope（审计事件统一字段）
审计事件通过 `AuditEmitter` 发往 `audit.events`（Redis Stream），最终落库到 `audit_events` 表。

推荐固定字段（与现有 emitter 对齐）：
- `event_id`（UUID）
- `schema_version`
- `event_time`（epoch seconds 字符串）
- `event_type`（字符串）
- `request_id`（UUID 字符串）
- `session_id` / `thread_id`（字符串）
- `span_id` / `parent_span_id`（UUID 字符串，允许空）
- `component`（建议：`job|agent|node|tool|llm|rag` 等）
- `actor_type`（`service|agent|user|system`）
- `actor_id`（如 `agent-api|agent-worker|rag-service`）
- `payload_json`（小 JSON；大内容走 artifacts/blob，只在 payload 放引用）


## 一、异步 Job 上树（物理挂载）

### 1) job_span（顶层 span）如何创建
当异步任务被创建/入队时，平台应至少发出一条 `job_queued`（或 `job_started`）事件，其特征为：
- `request_id = job_id`
- `span_id = job_id`
- `parent_span_id = ""`（空，表示顶层）
- `component = "job"`
- `payload` 中包含：`agent_key/title/queue/attempt/...`

审计落库层（`AuditPersistenceService`）需要在处理 job 事件时创建/更新一条 `agent_spans` 记录：
- `span_id = job_id`
- `request_id = job_id`
- `parent_span_id = NULL`
- `span_type = "job"`
- `node_name = "job"`（或 `Async Job`）
- `meta`：写入 `agent_key/title/arq_job_id/...`

> 注意：`span_type` 使用 `job`，避免与 DeepAgent 内部工具名 `task` 混淆。

### 1.1) job 生命周期“阶段节点”（少量、可控）
为让 Timeline 树在 **不爆炸节点数** 的前提下更可读，平台在落库时会从 `job_*` 事件 **派生少量阶段子 span**（不是事件本身变成节点）：

- `job_phase:queued`（`span_type="job_phase"`，`node_name="Queued"`）：从 `job_queued` 开始，到 `job_started` 结束
- `job_phase:execute`（`span_type="job_phase"`，`node_name="Running"`）：从 `job_started` 开始，到 `job_completed/job_failed/job_cancelled/job_timed_out` 结束
- `job_phase:waiting_approval`（`span_type="job_phase"`，`node_name="Waiting Approval"`）：从 `job_waiting_approval` 开始，到 `job_resumed` 结束（可选，仅 HITL 场景）

ID 约定（幂等，可重复计算）：
- `queued_span_id = uuid5(job_id, "job_phase:queued")`
- `execute_span_id = uuid5(job_id, "job_phase:execute")`
- `wait_span_id = uuid5(job_id, "job_phase:waiting_approval")`

> 说明：`job_progress` 仍然只作为事件存在（Event 列表可见），不作为树节点。


### 2) job 生命周期事件类型（建议最小集合）
这些事件用于审计与 UI 状态追踪，全部挂在 `span_id = job_id` 上：

- `job_queued`：API 入队成功后
  - payload：`queue/arq_job_id?/title/input_digest/config_digest`
- `job_started`：worker 真正开始执行（拿到 job）
  - payload：`worker_id/attempt/started_at`
- `job_progress`：执行中进度（可多次）
  - payload：`seq/progress/stage/message/eta_seconds?`
- `job_completed`：完成（终态）
  - payload：`result{type,url,label}/duration_ms/audit_url?/artifacts?`
- `job_failed`：失败（终态，含进入 graph 前失败）
  - payload：`error_class/error_message/retryable?/duration_ms`
- `job_cancel_requested`：用户/API 请求取消
  - payload：`reason?`
- `job_cancelled`：worker 确认取消（终态）
  - payload：`reason?/duration_ms`
- `job_timed_out`：超时（终态）
  - payload：`timeout_seconds/duration_ms`
- `job_waiting_approval`：HITL 中断并进入等待审批（非终态）
  - payload：`interrupt_data?/policy_id?/action_type?`
- `job_resumed`：HITL 审批通过/拒绝后继续执行（非终态）
  - payload：`decision/actor_id?`

> 说明：平台已有 SSE/任务流事件（`task_progress/task_completed/...`）可继续保留；审计事件建议用 `job_*` 与深层 agent 工具 `task` 解耦。


### 3) job 与 agent tracing 如何“挂载成树”
目标树结构：

`job_span (span_id=job_id)`  
└── `root_chain_span (span_id=LangChain root run_id)`  
    └── `node/tool/llm/...`

**物理挂载规则：**
- 当同一个 `request_id` 下出现第一个“根 chain span”（其 `parent_span_id` 为空，且 `span_type="chain"`）时：
  - 若 `job_span` 已存在：将该 chain span 的 `parent_span_id` 更新为 `job_id`
  - 若 `job_span` 尚未落库（乱序）：先保持该 chain span 仍为 root（`parent_span_id=NULL`），当后续 `job_*` 事件落库创建出 `job_span` 后，再把这些“根 chain span”统一挂到 job 下（同一个 `request_id` 内的 post-hoc 重连）

**为什么只挂 root chain？**
- LangChain 的其它 spans 已经有正确父子关系，挂 root chain 即可把整棵 agent 树整体接到 job 下，且不破坏 LangChain 原生 run_id 拓扑。


### 4) “可回溯原生链路”的要求
物理挂载会把 root chain 的 `parent_span_id` 从 `NULL` 改为 `job_id`。

为支持随时回看“未挂载前”的原生形态，建议在被挂载的 root chain span 的 `meta` 中写入：
- `meta.raw_parent_span_id`：挂载前的 parent（通常为 `null`）
- `meta.mounted_under_job = true`
- `meta.job_id = <job_id>`

这样：
- 默认 UI 用 DB 的 `parent_span_id` 展示“真实调用层级（包含 job）”
- 需要“原生视图”时，可以用 `raw_parent_span_id` 重建（或提供一个后端/前端开关）


### 5) run 状态与 job 状态的关系
异步模式下 `request_id == job_id`，因此：
- job 的终态（completed/failed/cancelled/timeout）应驱动 `agent_runs.status/ended_at`
- agent tracing 的 `run_finished/run_failed/run_interrupted` 仍可作为补充来源（例如 tool/llm 失败）

建议规则：
- `job_started`：确保 `agent_runs` 存在并置为 `running`
- `job_completed`：置 `succeeded`
- `job_failed`：置 `failed`（写 `error_message/error_code`）
- `job_cancelled`：置 `cancelled`（或复用 `interrupted`，但更推荐新增 `cancelled` 语义）
- `job_timed_out`：置 `failed` 或 `timed_out`（如需独立枚举）


## 二、独立 RAG 服务上树（跨服务）

### 1) Context 透传协议（HTTP headers）
平台调用 rag-service 时，必须透传以下字段：
- `x-agent-platform-request-id: <uuid>`（同一次业务 run）
- `x-agent-platform-session-id: <uuid>`
- `x-agent-platform-thread-id: <uuid>`
- `x-agent-platform-parent-span-id: <uuid>`（RAG 要挂到谁下面）

可选：
- `x-agent-platform-job-id: <uuid>`（异步时可与 request_id 相同）
- `x-agent-platform-agent-key`
- `x-agent-platform-user-id`

**parent_span_id 的取值建议：**
- 若 RAG 在 LangGraph node 内触发：优先使用该 node 的 `metadata["span_id"]`（手动 node span）
- 若未来 RAG 封装成 LangChain Tool：使用 tool 的 `run_manager.run_id`（LangChain 原生 tool span）


### 2) rag-service 侧如何产出 spans/events 并上树
rag-service 收到请求后：
1) 生成 `rag_root_span_id = uuid4()`
2) 发出 RAG 根阶段开始/结束事件（建议复用现有落库逻辑，减少平台改动）：
   - `event_type = "langgraph_node_started"` / `"langgraph_node_finished"`
   - `request_id = header.request_id`
   - `span_id = rag_root_span_id`
   - `parent_span_id = header.parent_span_id`（关键）
   - payload：`graph_id="rag_service"`, `node_id="rag_call"`（或更细粒度）
3) 若需要更细粒度（retrieve/rerank/generate…），为每个阶段生成子 span（parent=rag_root_span_id），同样用 `langgraph_node_*` 事件即可。

> 说明：这里使用 `langgraph_node_*` 是为了复用平台现有的 span 创建/映射逻辑（event_type 包含 `node` 即可映射为 `span_type="node"`）。
> 若后续希望在 UI 中区分颜色/类型，可扩展 `span_type="rag"` 并同步更新 UI 映射。


### 3) rag-service 的审计事件如何回流
推荐走 **Redis Stream（audit.events）**：
- rag-service 增加 `REDIS_URL` 配置
- 引入（或复制）`AuditEmitter` 实现，直接往同一个 `audit.events` 写事件
- 平台现有 `AuditWorker` 统一消费落库

未来可扩展：
- Kafka：将 `AuditEmitter` 的 transport 抽象为 interface（Redis/Kafka/HTTP）
- HTTP：平台提供 `/audit/ingest` 接口，rag-service 直接 POST（更强隔离，但需要高可用）


## 三、实现清单（落地步骤）
### 平台侧（agent-platform-api）
1) 在任务创建/入队时（`/tasks/.../execute`）发 `job_queued`
2) 在 worker 启动/结束/失败/取消/进度更新处发 `job_*`
3) 审计落库层扩展：
   - 识别 `job_*` 事件并创建/更新 `span_type="job"` 的 span
   - 发现 root_chain_span 时执行“挂载到 job”
   - 支持 job 乱序：job_span 出现后对同 `request_id` 的根 chain 做 post-hoc 重连
4) UI：Timeline 增加 `job` 类型颜色/图标/命名（避免与 tool=task 混淆）

### RAG 服务侧（rag_service）
1) 统一读取 `x-agent-platform-*` headers，构造 `TraceContext`
2) 接入 `AuditEmitter` 并将事件写入同一 `audit.events`
3) 为 rag 调用/阶段生成 spans（推荐复用 `langgraph_node_*` 事件类型）


## 四、乱序与幂等
- 事件幂等：以 `event_id` 去重（DB 已有约束/逻辑）
- span 父子乱序：使用 `meta.pending_parent_id`（平台已实现收养逻辑）
- job 挂载乱序：job_span 落库后扫描同 `request_id` 的根 chain 并挂载（post-hoc 更新 parent_span_id）


## 五、安全与数据体量
- payload 仅放摘要/引用，避免写入敏感数据与超大 JSON
- 大对象通过 artifacts/blob 存储，payload 放 `url/blob_id/sha256`
