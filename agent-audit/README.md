# agent-audit SDK 使用说明

> 面向 Agent 平台的审计采集 SDK，默认写入 Redis Streams（`audit.events`），
> 支持 LangChain / LangGraph 运行链路埋点，后续可扩展 Kafka 等传输层。

## 1. 安装 / 引用

### 1.1 在本仓库内使用

```bash
# 方式 A：PYTHONPATH 引入
export PYTHONPATH=$PYTHONPATH:/path/to/agent-audit

# 方式 B：editable 安装
pip install -e /path/to/agent-audit
```

### 1.2 依赖

```toml
# agent-audit/pyproject.toml
dependencies = ["redis>=5.0.0"]

# 如需 LangChain 回调
extras: langchain = ["langchain-core>=0.2.0"]
```

---

## 2. 核心概念

- **request_id**：业务级 Run ID（用于跨 span 关联一次请求/任务）
- **span_id**：单次调用/节点的唯一 ID
- **parent_span_id**：父 span（形成调用树）
- **component**：来源组件（agent / node / tool / llm / middleware 等）

---

## 3. 快速开始（直接写事件）

```python
import redis.asyncio as aioredis
from agent_audit.emitter import AuditEmitter

redis = aioredis.from_url("redis://localhost:6379", decode_responses=False)
emitter = AuditEmitter(redis=redis)

await emitter.emit(
    event_type="run_started",
    request_id="your-request-id",
    span_id=None,
    session_id="session-id",
    thread_id="thread-id",
    component="agent",
    payload={"root_agent_name": "data_agent"},
)
```

默认写入 Stream：`audit.events`

---

## 4. LangChain / LangGraph 集成

### 4.1 LangChain 回调（LLM / Tool）

```python
from agent_audit.emitter import AuditEmitter
from agent_audit.instrumentation.langchain import AuditCallbackHandler

emitter = AuditEmitter(redis=redis)
audit_cb = AuditCallbackHandler(emitter=emitter)

config = {
    "callbacks": [audit_cb],
    "metadata": {
        "request_id": "your-request-id",
        "session_id": "session-id",
        "thread_id": "thread-id",
    },
}
```

> `AuditCallbackHandler` 会发出 `llm_called / llm_output_received / tool_call_requested / tool_call_executed / tool_failed` 等事件。

### 4.2 LangGraph 节点（Node）

```python
from agent_audit.instrumentation.langgraph import node_wrapper

@node_wrapper("list_tables", graph_id="sql_agent")
async def list_tables_node(state, config):
    # 正常业务逻辑
    return {"ok": True}
```

**关键点：**

- `@node_wrapper` **不建议**在模块 import 时传入 `emitter`（避免事件循环冲突）。
- 运行时需要能获取 emitter，推荐方式是 **通过 callbacks 自动解析**：
  - 在上层 config 中注入 `AuditCallbackHandler(emitter=...)`
  - `node_wrapper` 会从 `callbacks` 中解析 `emitter`

如需显式传入，也支持：

```python
config["audit_emitter"] = emitter
```

---

## 5. 审计事件字段约定（Redis Streams）

每条事件写入 Redis Stream 字段：

- `event_id` / `schema_version` / `event_type` / `event_time`
- `request_id` / `session_id` / `thread_id`
- `span_id` / `parent_span_id`
- `component` / `actor_type` / `actor_id`
- `payload_json`（序列化后的 JSON）

---

## 6. Worker 消费与落库

`AuditWorker` 从 `audit.events` 消费事件并持久化（通过 `persist_callback` 注入）。

```python
from agent_audit.worker import AuditWorker
from agent_core.events import RedisEventBus

bus = RedisEventBus(redis_url="redis://localhost:6379")

async def persist_callback(events):
    # 你的落库逻辑（如写入 Postgres）
    ...

worker = AuditWorker(bus, persist_callback=persist_callback)
await worker.start()
```

---

## 7. 常见问题

**Q1: 看不到 `langgraph_node_*` 事件？**  
A: 确保上层 config 注入了 `AuditCallbackHandler`（`callbacks` 列表），
`node_wrapper` 会从回调中解析 emitter。

**Q2: 为什么不要在 import 时创建 Redis 连接？**  
A: LangChain/LangGraph 运行时可能跨事件循环，import 时创建的连接易导致
“attached to a different loop”。建议运行时创建 emitter。

**Q3: parent_span_id 外键错误？**  
A: 若 parent span 尚未落库，可先写入 `meta["pending_parent_id"]`，
待 parent 出现后统一补链（已在平台侧落库逻辑中处理）。

---

## 8. Kafka 扩展（预留）

`pyproject.toml` 已预留 `kafka` extras（如 `aiokafka`），
后续可在 `emitter` 中引入可插拔 transport。

---

## 9. 审计表建表 SQL（PostgreSQL）

> 说明：以下为 **agent-audit** 在平台侧落库所需核心表结构（与 `agent-platform-api/app/models/db_models.py` 对齐）。
> 若你只需要事件流，不落库可跳过。  
> 默认使用 `pgcrypto` 的 `gen_random_uuid()`，也可由应用层生成 UUID。

```sql
-- 需要 UUID 生成函数
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1) 运行主表
CREATE TABLE IF NOT EXISTS agent_runs (
  request_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id VARCHAR(100),
  thread_id VARCHAR(100),
  root_agent_name VARCHAR(100),
  entrypoint VARCHAR(200),
  initiator_type VARCHAR(50),
  initiator_id VARCHAR(100),
  env VARCHAR(20) DEFAULT 'prod',
  started_at TIMESTAMPTZ DEFAULT now(),
  ended_at TIMESTAMPTZ,
  status VARCHAR(20) DEFAULT 'running',
  error_code VARCHAR(50),
  error_message TEXT,
  tags JSONB
);

-- 2) Span 表（节点 / LLM / tool）
CREATE TABLE IF NOT EXISTS agent_spans (
  span_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id UUID NOT NULL REFERENCES agent_runs(request_id),
  parent_span_id UUID REFERENCES agent_spans(span_id),
  span_type VARCHAR(50) NOT NULL,           -- tool / chain / llm / node
  agent_name VARCHAR(100),
  subagent_kind VARCHAR(50),
  graph_id VARCHAR(100),
  node_id VARCHAR(100),
  node_name VARCHAR(100),
  attempt INT DEFAULT 1,
  started_at TIMESTAMPTZ DEFAULT now(),
  ended_at TIMESTAMPTZ,
  status VARCHAR(20) DEFAULT 'running',
  input_blob_id UUID,
  output_blob_id UUID,
  meta JSONB
);

-- 3) 审计事件流
CREATE TABLE IF NOT EXISTS audit_events (
  event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id UUID NOT NULL REFERENCES agent_runs(request_id),
  span_id UUID REFERENCES agent_spans(span_id),
  session_id VARCHAR(100),
  thread_id VARCHAR(100),
  event_time TIMESTAMPTZ DEFAULT now(),
  event_type VARCHAR(100) NOT NULL,
  actor_type VARCHAR(50),
  actor_id VARCHAR(100),
  component VARCHAR(50),
  target_type VARCHAR(50),
  target_id VARCHAR(100),
  severity VARCHAR(20) DEFAULT 'info',
  decision VARCHAR(50),
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  payload_blob_id UUID,
  prev_hash VARCHAR(200),
  hash VARCHAR(200)
);

-- 4) Tool 审计
CREATE TABLE IF NOT EXISTS tool_audits (
  tool_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id UUID NOT NULL REFERENCES agent_runs(request_id),
  span_id UUID REFERENCES agent_spans(span_id),
  session_id VARCHAR(100),
  thread_id VARCHAR(100),
  tool_name VARCHAR(200) NOT NULL,
  tool_version VARCHAR(50),
  request_time TIMESTAMPTZ DEFAULT now(),
  response_time TIMESTAMPTZ,
  status VARCHAR(20) DEFAULT 'pending',
  side_effect_level VARCHAR(20),
  resource JSONB,
  input_blob_id UUID,
  output_blob_id UUID,
  input_digest TEXT,
  output_digest TEXT,
  error JSONB,
  approval_id UUID
);

-- 5) 大对象 / Payload 存储
CREATE TABLE IF NOT EXISTS audit_blobs (
  blob_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMPTZ DEFAULT now(),
  content_type VARCHAR(100) DEFAULT 'text/plain',
  compression VARCHAR(20),
  encrypted BOOLEAN DEFAULT false,
  sha256 VARCHAR(64),
  content BYTEA
);

-- 6) HITL 审批
CREATE TABLE IF NOT EXISTS approval_requests (
  approval_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id UUID NOT NULL REFERENCES agent_runs(request_id),
  span_id UUID REFERENCES agent_spans(span_id),
  requested_at TIMESTAMPTZ DEFAULT now(),
  policy_id VARCHAR(100),
  action_type VARCHAR(50),
  risk_level VARCHAR(20),
  status VARCHAR(20) DEFAULT 'pending',
  proposed_action_blob_id UUID
);

CREATE TABLE IF NOT EXISTS approval_decisions (
  decision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  approval_id UUID NOT NULL REFERENCES approval_requests(approval_id),
  decided_at TIMESTAMPTZ DEFAULT now(),
  decider_id VARCHAR(100),
  decision VARCHAR(20) NOT NULL,
  reason TEXT,
  edited_action_blob_id UUID
);

-- 可选：父子 Span 外键延迟检查（避免乱序事件导致 FK 错误）
ALTER TABLE agent_spans
  DROP CONSTRAINT IF EXISTS agent_spans_parent_span_id_fkey;
ALTER TABLE agent_spans
  ADD CONSTRAINT agent_spans_parent_span_id_fkey
  FOREIGN KEY (parent_span_id) REFERENCES agent_spans(span_id)
  DEFERRABLE INITIALLY DEFERRED;
```

> 建议索引：
> - `audit_events(request_id, event_time)`
> - `agent_spans(request_id)`
> - `tool_audits(request_id)`
