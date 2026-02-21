## 1. 背景与总目标

你现有 CV 系统包含：

- **VA (video-analyzer)**：C++/Triton/ORT/TensorRT 推理，含多阶段匈牙利匹配、OCSort 追踪、零拷贝 GPU pipeline 等。
- **CP (controlplane)**：负责源管理、pipeline 编排、模型配置、追踪配置等。
- **前端 web-front**：配置管理 + 分析视图 + 推流播放。

新建的 **`agent` Python 服务** 目标：

1. 把复杂的 CP/VA 操作抽象为 **自然语言 + Agent 工具调用**，降低你和其他用户的操作复杂度。
2. 使用 **最新 LangChain 1.0.8 + LangGraph 1.0.3** 提供的 agent 能力，构建支持：
   - 多轮对话
   - 工具自动调用（ReAct 模式）
   - 状态持久化（checkpoint / threads）
   - 中断 / 人机协同（危险操作前停下来让你确认）[PyPI+2LangChain 文档+2](https://pypi.org/project/langgraph/)
3. 以 **独立 Docker 服务** 形式部署，不侵入 VA/CP，实现松耦合。

------

## 2. 需求分析

### 2.1 核心功能需求

1. **控制平面操作 Agent**
   - 自然语言创建 / 修改 / 删除分析任务（pipeline）。
   - 切换模型（检测/分割/重识别）、调整阈值/输入尺寸/batch。
   - 管理追踪器（OCSort GPU 开关、匈牙利多阶段参数等）。
   - 控制 pipeline 启停、切换订阅源。
2. **观测 & 排障 Agent**
   - 查询某 pipeline 的状态、QPS、延迟、最近错误。
   - 查询 GPU/显存/CPU 指标（Prometheus / CP 代理）。
   - 结合日志 + 指标分析疑似问题并给出排障建议。
3. **配置生成与校验 Agent**
   - 从自然语言需求生成 pipeline 配置草案（YAML/JSON）。
   - 对现有配置做静态检查（显存风险、吞吐瓶颈、模型兼容性）。
4. **有状态对话工作流**
   - 同一会话内多轮演进配置，例如：
     - “帮我先查显存暴涨原因 → 再生成调参方案 → 再执行改动”。

### 2.2 非功能需求

- **高可用**：Agent 崩溃不影响 VA/CP 运行。
- **安全**：危险操作必须“建议 + 确认”；权限沿用 CP 体系。
- **可观测**：有完整调用日志与指标；可接 LangSmith 做调试/可视化。[LangChain 文档+1](https://docs.langchain.com/?utm_source=chatgpt.com)
- **可演进**：从单 Agent MVP 平滑升级到多 Agent / RAG / 深度工作流。

------

## 3. 系统级架构

### 3.1 微服务拓扑

新引入服务：`agent`（Python）

- 技术栈：Python 3.11+、FastAPI、LangChain 1.0.8、LangGraph 1.0.3。[LangChain 更新日志+3PyPI+3PyPI+3](https://pypi.org/project/langchain/?utm_source=chatgpt.com)
- 对外暴露：
  - `POST /v1/agent/invoke`：一问一答。
  - 后续：`/v1/agent/threads/{thread_id}/invoke`：持久线程，有 checkpoint。
- 向内调用：
  - CP：HTTP/gRPC API（源、pipeline、模型、追踪配置、状态）。
  - VA：必要状态查询（可选）。
  - Prometheus：指标查询（可选）。
  - 文档/RAG 存储（后期）。

各服务边界：

- **CP 仍是唯一“真相源”**：所有配置变更只能通过 CP API。
- **agent 禁止直接写数据库**：只做高级客户端 + 智能编排。
- **VA 仅暴露状态/运行信息**，不接受直接配置写入。

### 3.2 技术组件与版本

- `langchain==1.0.8`：Agent 高层模式、工具抽象、RAG 等。[PyPI+1](https://pypi.org/project/langchain/?utm_source=chatgpt.com)
- `langgraph==1.0.3`：StateGraph、checkpoint、线程、human-in-the-loop 等低层 agent 编排。[PyPI+2LangChain 文档+2](https://pypi.org/project/langgraph/)
- `langgraph-prebuilt==1.0.5`：预定义 ReAct agent 模板（`create_react_agent`）。[Zenn+3GitHub+3エクスチュア株式会社+3](https://github.com/langchain-ai/langgraph/releases?utm_source=chatgpt.com)
- `langchain-openai==1.0.3`：接 OpenAI / 兼容 OpenAI 模型。[PyPI+1](https://pypi.org/project/langchain-openai/?utm_source=chatgpt.com)
- `fastapi` + `uvicorn`：HTTP API 服务。[LangChain 文档+1](https://docs.langchain.com/?utm_source=chatgpt.com)
- `httpx`：调用 CP / VA / Prometheus。
- `pydantic v2` + `pydantic-settings`：配置和数据模型（LangChain 1.x 已全面切换到 pydantic v2 生态）。[LangChain 更新日志+1](https://changelog.langchain.com/?date=2025-03-01&page=6&utm_source=chatgpt.com)

------

## 4. agent 服务内部架构

### 4.1 分层与模块

建议在 `cv/agent/` 下新建一个独立 Python 模块 `cv_agent`，采用三层架构：

1. **接口层（server/API）**
   - 使用 FastAPI 提供 REST / （后续）WebSocket：
     - `POST /v1/agent/invoke`
     - `POST /v1/agent/threads/{thread_id}/invoke`
   - 负责：
     - 认证信息提取（user_id, role）并注入 agent state。
     - 将 HTTP 请求转换为 LangGraph 的输入（messages/state/thread_id）。
2. **编排层（graph）**
   - 使用 LangGraph 1.0.3：
     - 初始阶段利用 `langgraph.prebuilt.create_react_agent` 快速搭一个 ReAct agent（内部是 `agent` + `tools` 的图）。[LangChain 文档+4PyPI+4エクスチュア株式会社+4](https://pypi.org/project/langgraph/)
     - 中后期使用 Graph API (`StateGraph`) 自定义：
       - Router 节点
       - PipelineAgent / DebugAgent / ModelAgent 节点
       - ToolExecutor 节点
       - 人机协同节点（interrupt + resume）。
3. **工具与基建层（tools + store + config）**
   - `tools/`：封装 CP / VA / Prometheus / 文档检索为 LangChain 工具。
   - `config.py`：Pydantic Settings 从环境变量加载 LLM/下游地址/超时等。
   - `store/checkpoint.py`：封装 LangGraph checkpoint（Memory/SQLite/MySQL）。
   - `logging/`（可选）：统一日志封装与 ID 打点。

### 4.2 目录结构

```
agent/
  cv_agent/
    __init__.py
    config.py           # BaseSettings，LLM & CP/VA 地址等
    tools/
      __init__.py
      pipelines.py      # pipeline 管理相关工具
      models.py         # 模型/追踪器配置工具
      metrics.py        # 指标查询工具
      debug.py          # 日志、排障工具
    graph/
      __init__.py
      control_plane.py  # 基于 create_react_agent 的主 Agent；后续扩展 StateGraph
      router.py         # 多 Agent 路由；扩展用
      debug_agent.py    # 专用调试 Agent；扩展用
    server/
      __init__.py
      api.py            # FastAPI 入口，挂载 /v1/agent/*
    store/
      __init__.py
      checkpoint.py     # Checkpointer 封装（Memory/SQLite/MySQL）
  Dockerfile
  requirements.txt
  docker-compose.agent.yml  (可合并进你的总 compose)
  .env.example
  README.md
```

------

## 5. LangChain & LangGraph 使用方案（基于最新 1.x）

### 5.1 依赖安装策略

参照官方安装文档：[LangChain 文档+2PyPI+2](https://docs.langchain.com/oss/python/langchain/install?utm_source=chatgpt.com)

```
pip install -U langchain==1.0.8 langgraph==1.0.3 \
               langgraph-prebuilt==1.0.5 \
               langchain-openai==1.0.3 \
               fastapi uvicorn[standard] httpx \
               pydantic pydantic-settings python-dotenv
```

LangChain 1.0 强调“核心 + provider 包”模式，`langchain-openai` 做 OpenAI 集成，后面如果你用 Anthropic / Groq / Ollama 也有对应包，可替换掉 `langchain-openai` 而不影响 Agent 代码结构。[LangChain 文档+2GitHub+2](https://docs.langchain.com/oss/python/langchain/install?utm_source=chatgpt.com)

### 5.2 MVP：基于 `create_react_agent` 的控制平面 Agent

理由：

- LangGraph 官方建议简单场景用 **预构建 ReAct agent** 起步，再在需要时改成自定义 StateGraph。[Google AI for Developers+4PyPI+4エクスチュア株式会社+4](https://pypi.org/project/langgraph/)
- 你的初版需求主要是“理解自然语言 + 调 CP 工具”，典型 ReAct 模式。

设计：

- LLM：
  - 使用 `langchain-openai` 的 `ChatOpenAI`（或者后续用 `create_agent` 也可以）。[python.langchain.com+1](https://python.langchain.com/v0.1/docs/get_started/installation/?ref=journal.hexmos.com&utm_source=chatgpt.com)
- Tools：
  - 从 `cv_agent.tools` 中导入 `list_pipelines`, `get_pipeline_status`, `create_pipeline`, `update_tracker_config` 等。
  - 使用 LangChain 1.0 的工具装饰器 / factory，配合 Pydantic v2 类型，保证工具调用参数结构化稳定。[PyPI+3python.langchain.com+3LangChain 更新日志+3](https://python.langchain.com/v0.1/docs/get_started/installation/?ref=journal.hexmos.com&utm_source=chatgpt.com)
- Agent：
  - 在 `graph/control_plane.py` 里调用 `create_react_agent(model=llm, tools=TOOLS, state_modifier=...)`。
  - Agent 的输入为 `{"messages": [...]}`，输出为包含 messages 的 state，最终回复是最后一条 `AIMessage`。[PyPI+2Zenn+2](https://pypi.org/project/langgraph/)

### 5.3 后续：自定义 StateGraph（多 Agent）

当你要拆出子 Agent（PipelineAgent / DebugAgent / ModelAgent）时，改用 LangGraph Graph API：

- 定义 `AgentState`（Pydantic）：
  - `messages: list[BaseMessage]`
  - `task: str | None`
  - `user: dict`（id, role, permissions）
  - `cv_context: dict`（当前 pipeline / 模型 / GPU 快照）
  - `plan: list[str]`（复杂任务步骤）
  - `pending_tools: list[...]`
- 用 `StateGraph(AgentState)` 定义节点：
  - `router`：理解意图，决定走哪个子 Agent。
  - `pipeline_agent`：负责 pipeline 相关操作。
  - `debug_agent`：负责日志/指标分析。
  - `tool_executor`：统一执行工具，并更新 state.messages。
- 再用 `graph.compile(checkpointer=...)` 生成 `CompiledGraph`，在 API 层用 `.invoke()` / `.stream()` 调用。[LangChain 文档+2langchain-ai.github.io+2](https://docs.langchain.com/oss/python/langgraph/quickstart?utm_source=chatgpt.com)

------

## 6. Tools 设计（基于 LangChain 1.0 工具体系）

### 6.1 设计原则

- 使用 **Pydantic v2** 定义工具参数，LangChain 1.0 已围绕其做了优化。[LangChain 更新日志+2Qiita+2](https://changelog.langchain.com/?date=2025-03-01&page=6&utm_source=chatgpt.com)
- 工具职责单一，保证：
  - 查询工具（只读）安全可重复调用。
  - 变更工具（写操作）必须显式确认 + 支持 dry-run。
- 工具命名清晰，对 LLM 友好，例如：
  - `list_pipelines`
  - `get_pipeline_status`
  - `create_pipeline`
  - `update_pipeline_config`
  - `toggle_ocsort_gpu`
  - `update_hungarian_params`
  - `get_pipeline_metrics`
  - `get_pipeline_logs`

### 6.2 工具分层

1. **CP 工具**
   - `pipelines.py`：
     - 管理 pipeline 生命周期和配置（调用 CP API）。
   - `models.py`：
     - 管理模型选择、版本切换、追踪器配置。
   - `debug.py`：
     - 查询日志、最近错误、异常统计。
2. **监控工具**
   - `metrics.py`：
     - 从 Prometheus / CP 代理获取 GPU/显存/任务指标。
   - 结合 agent 的 reasoning 逻辑推导可能瓶颈。
3. **RAG 工具（后期）**
   - 针对你的 docs / README / pipeline 模板构建一个检索器：
     - `search_cv_docs(query)`: 用于解释字段含义、推荐配置模板。
   - 用 LangChain 的 Retrieval + LangGraph 的 Agentic RAG 设计，把“读文档”纳入 Agent 决策路径。[LangChain 文档+2python.langchain.com+2](https://docs.langchain.com/?utm_source=chatgpt.com)

------

## 7. 状态管理与 Checkpoint（基于 LangGraph 1.0.3）

### 7.1 为什么要 Checkpoint

LangGraph 1.0 的核心卖点就是 **durable execution + human-in-the-loop + comprehensive memory**：
 每一步执行后自动把 state 存入 checkpoint，可支持：

- 长对话/长任务：线程（thread）级别连续记忆。
- 异常恢复：失败后从最近 checkpoint 重试。
- 人机协同：危险动作前中断，等待外部确认。[PyPI+2LangChain 更新日志+2](https://pypi.org/project/langgraph/)

### 7.2 实现策略

- 开发阶段：
  - 用内存 checkpointer（如 `MemorySaver`）做 PoC，方便调试。[langchain-ai.github.io+1](https://langchain-ai.github.io/langgraph/reference/?utm_source=chatgpt.com)
- 生产阶段：
  - 使用 SQLite/Postgres/MySQL checkpointer 实现：
    - 建独立库 `cv_agent_checkpoint`，避免污染业务库。
    - 该库仅 agent 服务可写；不对外暴露。
  - 注意官方安全提示：checkpoint 若被恶意篡改，可能影响反序列化行为，因此必须限制访问主体、定期备份。[PyPI+1](https://pypi.org/project/langgraph/)

API 交互模式：

- 前端为每个“会话”生成一个 `thread_id`（可以用任务 ID / 摄像头 ID 组合）。
- 调用 `POST /v1/agent/threads/{thread_id}/invoke` 时，agent 会从对应 checkpoint 拿之前的 state，执行下一 step 再写回。

------

## 8. 安全、权限与审计

### 8.1 身份透传

- 前端调用 Agent API 时，在 header 中附带：
  - `X-User-Id`, `X-User-Role`, `X-Tenant` 等。
- API 层把这些信息注入 LangGraph state（如 `state.user`）。
- Tools 调用 CP API 时带上这些信息，让 CP 做真正的权限控制。

### 8.2 危险操作控制（人机协同）

对于 `delete_pipeline` / 批量更新 / 切模型等高风险工具：

1. Agent 首先调用：
   - 只读工具 + 写操作工具的 dry-run 模式，生成一个“计划 / diff”。
2. Graph 进入一个 **中断节点**（使用 LangGraph 的 human-in-the-loop 模式），返回：
   - 自然语言总结。
   - 结构化 diff 数据。
3. 前端展示 diff，并给出 “确认/取消” 按钮：
   - 确认 → 前端继续调用 Agent graph，带 `confirm=true`。
   - 取消 → Graph 收到后终止/回滚计划。[PyPI+2langchain-ai.github.io+2](https://pypi.org/project/langgraph/)

### 8.3 审计与可观测性

- 审计日志：
  - CP 侧记录：“由 Agent(LLM) + user_id 触发的操作”，包括工具名、关键参数。
- Agent 日志：
  - 每次调用记录：
    - thread_id, user_id, 所调用工具、时间、结果摘要。
  - 可选：接入 LangSmith 记录 run trace 和图形化调试。[LangChain 文档+1](https://docs.langchain.com/?utm_source=chatgpt.com)

------

## 9. 部署设计（Docker 为主）

这里先讲原则，不写具体 Dockerfile（你之前已经要了一版代码实现）。

### 9.1 镜像构建原则

- 基础镜像：`python:3.11-slim`（3.13 也可，LangGraph 已支持到 3.13）。[PyPI+1](https://pypi.org/project/langgraph/)
- 生产镜像要求：
  - 禁用 root：创建 `app` 用户运行服务。[langchain-ai.github.io+1](https://langchain-ai.github.io/langgraph/how-tos/react-agent-from-scratch/?utm_source=chatgpt.com)
  - 使用 `.dockerignore` 排除无关文件（.git、logs、venv 等）。
  - 先复制 `requirements.txt` 再安装，利用 layer cache。
  - 启动命令：
    - 小规模可直接用 `uvicorn`；
    - 生产建议 `gunicorn + uvicorn` worker（多进程）。[LangChain 文档+2Zenn+2](https://docs.langchain.com/oss/python/langgraph/quickstart?utm_source=chatgpt.com)

### 9.2 Compose / K8s 拓扑

- `cv-agent` 与 `controlplane`、`video-analyzer` 加入同一网络（例如 `cv-net`）。
- 通过环境变量配置 CP/VA 的服务地址：
  - `AGENT_CV_CP_BASE_URL=http://controlplane:8080`
  - `AGENT_CV_VA_BASE_URL=http://video-analyzer:8080`
- 在总 `docker-compose.yml` 中：
  - `cv-agent` 使用 `depends_on: [controlplane]`。
  - 对外暴露端口，例如 `18080:8000`（本地调试使用）。

------

## 10. 演进路线（基于最新 LangChain/LangGraph 能力）

### Phase 1：MVP（单 ReAct Agent + 基础工具）

- 依赖：`langchain==1.0.8`, `langgraph==1.0.3`, `langgraph-prebuilt==1.0.5`, `langchain-openai==1.0.3`。[PyPI+3PyPI+3PyPI+3](https://pypi.org/project/langchain/?utm_source=chatgpt.com)
- 实现：
  - FastAPI 暴露 `/v1/agent/invoke`。
  - 使用 `create_react_agent` + 几个基础工具（列出/查询 pipeline）。
  - Docker 部署 + 前端一个简单聊天框。
- 价值：
  - 打通“自然语言 → 工具 → CP 实际动作”的闭环。

### Phase 2：更多工具 + Checkpoint 持久化

- 扩展工具集，覆盖：
  - pipeline CRUD
  - 模型/追踪切换
  - 指标/日志查询
- 引入持久化 Checkpoint（SQLite/PG/MySQL）和 `thread_id` 模式，真正做到多轮有状态对话。
- 前端支持按 “任务/摄像头” 查看历史对话线程与变更记录。

### Phase 3：自定义多 Agent StateGraph + RAG

- 使用 LangGraph Graph API 自定义：
  - Router + PipelineAgent + DebugAgent + ModelAgent；
  - 每个 Agent 专注一个子域。
- 引入 RAG：
  - 把 `docs/`、config 样例、API 文档做成知识库，Agent 先“读文档”再决定用什么工具，用 LangChain 1.0 的检索/Agentic RAG 模式。[LangChain 文档+2python.langchain.com+2](https://docs.langchain.com/?utm_source=chatgpt.com)
- 加强人机协同：
  - 所有危险操作统一走“生成计划 → interrupt → 用户确认 → resume”模式。

------

这一版设计已经完全围绕 **LangChain 1.0.8 + LangGraph 1.0.3 + langgraph-prebuilt 1.0.5** 的最新生态来写了，兼顾你现在 CV 项目的架构和未来扩展空间。