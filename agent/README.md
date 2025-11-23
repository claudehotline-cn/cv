# Agent 服务（cv_agent）

本目录包含基于 FastAPI + LangChain + LangGraph 实现的 ControlPlane Agent 服务，实现“自然语言 → 工具 → CP/VA 操作”的能力。

当前实现处于 **Phase 1（MVP）**，仅支持：

- 通过 ReAct Agent 调用只读工具：
  - `list_pipelines`
  - `get_pipeline_status`
  - `plan_update_pipeline_config`（仅 dry-run，生成配置变更 diff）
- 提供 HTTP 接口：
  - `GET /healthz`
  - `POST /v1/agent/invoke`
  - `POST /v1/agent/threads/{thread_id}/invoke`

## 1. 依赖与构建

### 1.1 本地安装（可选）

```bash
cd /home/chaisen/projects/cv
python -m venv .venv
source .venv/bin/activate
pip install -r agent/requirements.txt
uvicorn agent.main:app --reload --port 8000
```

### 1.2 Docker 镜像

Compose 环境使用 `docker/agent/Dockerfile` 构建镜像：

```bash
cd /home/chaisen/projects/cv
docker compose -f docker/compose/docker-compose.yml up -d --build agent
```

### 1.3 Checkpoint 后端配置

- 默认使用内存型 `MemorySaver`：
  - `AGENT_CHECKPOINT_BACKEND=memory`
- 可选 SQLite：
  - `AGENT_CHECKPOINT_BACKEND=sqlite`
  - `AGENT_CHECKPOINT_SQLITE_CONN=checkpoints.sqlite`（或 `:memory:` 等）
  - 需要在 agent 环境中额外安装 `langgraph-checkpoint-sqlite` 包；
  - 如导入失败会回退至 `MemorySaver`（日志中会给出告警）。
- MySQL：
  - 目前仅预留 `AGENT_CHECKPOINT_MYSQL_DSN` 配置字段；
  - 实际 MySQL 型 checkpoint 尚未实现，使用时会抛出异常。

## 2. 环境变量

主要配置由 `cv_agent.config.Settings` 管理，通过环境变量注入：

- `OPENAI_API_KEY`：OpenAI 兼容模型 API Key（可为空，空时走本地测试模式）。
- `AGENT_OPENAI_MODEL`：模型名，默认 `gpt-4o-mini`。
- `AGENT_CP_BASE_URL`：ControlPlane HTTP 基址，Compose 中默认为 `http://cp:18080`。
- `AGENT_REQUEST_TIMEOUT`：下游 HTTP 请求超时（秒），默认 10。
- `AGENT_LOG_LEVEL`：日志级别，默认 `INFO`。

## 3. HTTP 接口

### 3.1 健康检查

```bash
curl http://localhost:18081/healthz
```

### 3.2 一问一答 Agent 调用

```bash
curl -X POST http://localhost:18081/v1/agent/invoke \
  -H 'Content-Type: application/json' \
  -d '{
    "messages": [
      { "role": "user", "content": "请帮我列出当前所有 pipeline。" }
    ]
  }'
```

返回字段：

- `message`：Agent 的自然语言回复。
- `raw_state`：LangGraph 状态（当前用于调试，生产可按需裁剪）。

### 3.3 带 thread_id 的多轮对话调用

```bash
curl -X POST http://localhost:18081/v1/agent/threads/demo-thread/invoke \
  -H 'Content-Type: application/json' \
  -d '{
    "messages": [
      { "role": "user", "content": "后续对话都使用 demo-thread 这个线程。" }
    ]
  }'
```

内部使用 LangGraph 的 checkpoint 能力按 `thread_id` 维度保存对话状态；
当前实现基于 MemorySaver，仅在单进程生命周期内有效。

## 4. 本地测试模式（无 OPENAI_API_KEY）

为方便在开发/测试阶段验证工具链路，当环境中 **未配置 `OPENAI_API_KEY`** 时：

- Agent 不会调用远程 LLM；
- `/v1/agent/invoke` 会直接调用 CP 的 `/api/pipelines`，构造一条说明当前为“本地测试模式”的回复；
- 返回的 `raw_state.offline = true`，`raw_state.pipelines` 为从 CP 查询到的 pipeline 列表（可能为空）。

示例输出见：`docs/examples/agent_service_e2e.md`。

## 5. 工具列表（Phase 1）

所有工具定义在 `agent/cv_agent/tools` 下，并通过 `get_all_tools()` 统一导出。

- `list_pipelines`：
  - 调用 CP `/api/pipelines`；
  - 返回简化字段：`name`、`graph_id`、`default_model_id`。
- `get_pipeline_status`：
  - 调用 CP `/api/control/status?pipeline_name=xxx`；
  - 返回：`pipeline_name`、`phase`、`metrics`。
- `plan_update_pipeline_config`：
  - 从 `/api/pipelines` 中查询指定 pipeline 的当前配置；
  - 按给定 `new_graph_id` / `new_default_model_id` 生成 dry-run 变更计划（diff），不执行实际更新；
  - 为后续高危写操作的人机协同（确认前先展示 diff）提供基础数据。
- `plan_delete_pipeline` / `delete_pipeline`：
  - `plan_delete_pipeline`：基于 `/api/pipelines` 检查是否存在，并返回删除计划；不执行删除；
  - `delete_pipeline`：在 `confirm=false` 时仅返回删除计划；`confirm=true` 时调用 CP `DELETE /api/control/pipeline` 执行删除。
- `plan_hotswap_model` / `hotswap_model`：
  - `plan_hotswap_model`：检查 pipeline 是否存在，并返回包含 `node` 与 `model_uri` 的 hotswap 计划；
  - `hotswap_model`：在 `confirm=false` 时仅返回计划；`confirm=true` 时调用 CP `POST /api/control/hotswap` 执行模型切换。
- `plan_drain_pipeline` / `drain_pipeline`：
  - `plan_drain_pipeline`：检查 pipeline 是否存在，查询当前状态，并返回 drain 计划（包括 `timeout_sec`）；
  - `drain_pipeline`：在 `confirm=false` 时仅返回计划与当前状态；`confirm=true` 时调用 CP `POST /api/control/drain` 执行 drain。

> 约定：所有高危写操作工具都必须以 `plan_*` + `confirm=true` 两步配合使用，Agent 应在得到用户明确确认后才调用带 `confirm=true` 的执行型工具。

## 6. 集成测试脚本（control 协议）

位于 `agent/` 目录下，可在宿主机或 agent 容器内运行：

- `test_invoke_agent.py`：
  - 最小 `/v1/agent/invoke` 调用示例（不带 control）。
- `test_control_plan_delete.py`：
  - 使用 `/v1/agent/threads/{thread_id}/invoke` + `control` 字段，触发 `pipeline.delete` 的 plan 模式；
  - 通过 `AGENT_TEST_PIPELINE_NAME` 指定 pipeline 名称。
- `test_control_plan_drain.py`：
  - 使用 `/v1/agent/threads/{thread_id}/invoke` + `control` 字段，触发 `pipeline.drain` 的 plan 模式；
  - 可通过 `AGENT_TEST_PIPELINE_NAME` 与 `AGENT_TEST_DRAIN_TIMEOUT` 控制参数。

所有示例默认只执行 dry-run（plan 模式），不会实际修改系统状态。


后续 Phase 2 / Phase 3 将在此基础上扩展写操作工具、多 Agent StateGraph 与 RAG 工具。
