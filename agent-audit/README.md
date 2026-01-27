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
