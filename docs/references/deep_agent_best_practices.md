# LangChain DeepAgent 开发最佳实践指南

本文档基于对 `article_agent` (Deep Agent 架构文章生成版) 和 `agent_langchain` (Deep Agent 架构数据分析版) 的代码分析，总结了使用 LangChain DeepAgent 库开发高可靠性 Agent 系统的最佳实践。

## 1. 核心架构设计 (Architecture Patterns)

### 分层多智能体架构 (Hierarchical Multi-Agent)
推荐采用 **主智能体 (Main Agent) + 子智能体 (Sub-Agents)** 的分层结构。
*   **Main Agent**: 负责任务分发、流程编排、状态管理。它不直接执行具体工具，而是调用 Sub-Agent。
*   **Sub-Agent**: 专注特定领域任务（如 SQL 查询、Python 执行、文章撰写）。

### Sub-Agent 的两种实现模式

根据任务的确定性程度，选择不同的实现方式：

| 模式 | 实现类 | 适用场景 | 示例 |
| :--- | :--- | :--- | :--- |
| **LLM 驱动模式** | `CompiledSubAgent` | 任务灵活、步骤不固定、强依赖语义理解。 | `sql_agent`, `planner_agent`, `researcher_agent` |
| **固化流模式 (StateGraph)** | `StateGraph` | 步骤严格固定、对数据准确性要求极高、容易幻觉的场景。 | `python_agent`, `visualizer_agent`, `report_agent` |

> **最佳实践**: 对于关键的数据处理流程（如"先看数据再写代码"），不要依赖 LLM 自行决定调用顺序，应使用 `StateGraph` 将流程固化为代码逻辑（Code-First），仅在需要生成的环节调用 LLM。这能彻底解决幻觉和步骤跳过问题。

## 2. 状态管理与资源共享 (State Management & Resource Sharing)

### 全局唯一标识 (Analysis/Article ID)
*   **必须性**: 在多 Agent 协作中，必须有一个全局 ID (`analysis_id` 或 `article_id`) 贯穿始终，用于关联文件、数据和上下文。
*   **传递机制 (Config Propagation)**:
    *   **推荐方式**: 通过 LangChain/LangGraph 的 `config` 对象传递。前端发起请求时将 ID 放入 `config.configurable`，后端所有 Agent、Tool 和 Middleware 均可直接从 `config` 中读取，无需污染 Prompt 或函数签名。
    *   **Frontend**: 请求体包含 `{ "configurable": { "analysis_id": "..." } }`。
    *   **Backend**: 
        *   **Agent/Tool**: `config.get("configurable", {}).get("analysis_id")`
        *   **Middleware**: `runtime.config.get("configurable", {}).get("analysis_id")` 或 `runtime.context.get("analysis_id")`

### 共享存储 (Shared Store)
使用 `runtime.store`（LangGraph BaseStore）在 Middleware 间共享数据。

> **⚠️ 重要**: `ContextVar` 在异步 Middleware 环境中**不可靠**，跨 `await` 边界可能丢失上下文。必须使用 `runtime.store`。

**最佳实践**：在 Middleware 中使用**异步 API**（`aput`/`aget`），否则会报 `Synchronous calls to BatchedStore detected` 错误。

```python
# middleware.py
class AsyncStateMiddleware(AgentMiddleware):
    async def abefore_agent(self, state, runtime):
        thread_id = state.get("configurable", {}).get("thread_id")
        # 异步读取
        await runtime.store.aget(namespace=("shared",), key=thread_id)
        return state
```

### 文件系统与工作区 (Filesystem Backend)

DeepAgent 使用 `Backend` 抽象来管理文件资源的共享与隔离。正确配置 Backend 对于安全性和数据流转至关重要。

**推荐配置 (CompositeBackend)**：
```python
backend=lambda rt: CompositeBackend(
    default=FilesystemBackend(
        root_dir="/data/workspace",  # 此为容器内绝对路径
        virtual_mode=True            # ✅ 开启沙箱模式：限制 Agent 只能访问 root_dir 及其子目录
    ),
    routes={
        "/_shared/": StoreBackend(rt),  # 将特定路径路由到内存/Redis Store，用于跨 Agent 高速共享小文件
    }
)
```

**最佳实践**：
1.  **沙箱隔离**: 务必开启 `virtual_mode=True`，防止越权访问主机敏感文件（如 `/etc/passwd`）。
2.  **按 ID 隔离**: 建议按 `analysis_id` 创建子目录（如 `/data/workspace/artifacts/{analysis_id}/`），防止不同任务间文件冲突。
3.  **统一根目录**: 所有 Tool 的文件操作路径都应基于此根目录。

## 3. 提示词工程 (Prompt Engineering)

### 严格的流程控制
*   在 `MAIN_AGENT_PROMPT` 中明确定义标准工作流（SOP）。
*   使用 **"严禁..."**, **"必须..."** 等强硬措辞约束行为。
*   明确“完成条件”，例如“只有收到 `report_agent` 的 Markdown 输出才算结束”。

### 提示词纯净原则 (Clean Prompts)
*   **分离业务与基建**：Prompt 应专注于“做什么”和“怎么做”（业务逻辑），而不是“怎么传参”（基础设施）。
*   **无需手动传递 ID**：配置信息（如 `analysis_id`、`user_id`）应由代码层自动处理，**严禁**在 Prompt 中要求 LLM 手动提取或传递这些 ID。这能减少 Token 消耗并降低幻觉风险。

### 结构化输入输出
*   Sub-Agent 的 System Prompt 中应包含详细的参数说明和示例。
*   对于需要精确格式的输出（如 JSON），使用 Pydantic Model (`response_format`) 结合 Middleware 强制格式化。

### response_format 与 Agent 终止条件

在 DeepAgent/LangGraph 中，`response_format` 参数不仅控制输出格式，更重要的是**定义 Agent 的终止条件**。

#### 支持的类型
| 类型 | 示例 | 说明 |
| :--- | :--- | :--- |
| **Pydantic Model** | `MainAgentOutput` | ✅ 推荐。LLM 必须调用此"响应工具"才算完成。 |
| **ToolStrategy(Model)** | `ToolStrategy(MainAgentOutput)` | ✅ 推荐。将 Schema 包装为工具调用。 |
| **None** | `response_format=None` | ⚠️ 危险。行为不稳定，可能立即结束或无限循环。 |
| **str** | `response_format=str` | ❌ 不支持。框架会报错。 |

#### 行为对比
| 配置 | Agent 行为 |
| :--- | :--- |
| 有 `response_format` | LLM 必须调用"响应工具"才终止，行为可预测 |
| 无 `response_format` | LLM 输出纯文本即终止，可能过早结束或死循环 |

#### 最佳实践
```python
from langchain.agents.structured_output import ToolStrategy

class MainAgentOutput(BaseModel):
    """简化版：只保留必要字段，复杂数据由 Middleware 注入。"""
    summary: str = Field(description="任务完成后的简短总结")
    confidence: str = Field(description="low/medium/high")
    # chart/report 等数据由 FileContentInjectionMiddleware 从文件注入

response_format = ToolStrategy(MainAgentOutput)
```

> **注意**: 如果使用 Middleware 从文件系统注入 Chart/Report 等大数据，Schema 中就不需要包含这些字段，可以显著简化 LLM 的输出负担。

## 4. 工具设计与调用控制 (Tooling)

### 强制工具调用 (Forced Tool Calling)
对于必须执行动作的 Agent（如 `planner` 必须生成大纲），不要让 LLM 选择是否调用工具，而是使用 `tool_choice="required"` 或绑定特定工具名。
```python
# 示例: 强制 planner 必须调用 generate_outline_tool
planner_llm_forced = planner_llm.bind_tools(
    [generate_outline_tool],
    tool_choice={"type": "function", "function": {"name": "generate_outline_tool"}}
)
```

### 专注于原子能力
*   工具功能应单一且原子化（如 `db_run_sql` 只跑 SQL，不负责解释）。
*   复杂的逻辑组合应交给 Graph 或 Agent 编排。

### 上下文感知工具与全栈传递 (Context-Aware Tools & Full-Stack Propagation)

在 LangGraph 里，**运行时配置 (Runtime Config) ≠ Agent 初始化参数**。它是在每一次 `run` / `invoke` 时动态传入的上下文参数。

**典型用途**:
1.  **用户身份**: `user_id`, `session_id`
2.  **功能开关**: 前端传来的开关（如 `enable_chart_generation=true`）
3.  **动态模型**: 此次运行指定的模型（如 `model_name="gpt-4"`）
4.  **业务参数**: 风格、字数限制、目标语言
5.  **调试控制**: `trace=true`, debug 标记
6.  **资源配置**: `backend` 路径, `runtime.store` 命名空间

在 LangGraph CLI 部署模式下，`configurable` 参数是连接前端与后端工具的桥梁。

#### 1. 前端传递 (Frontend Request)
调用 LangGraph API (`POST /threads/{thread_id}/runs`) 时，将业务 ID 放入 `config.configurable` 字段。

```javascript
// 前端请求示例
await fetch(`/api/threads/${threadId}/runs`, {
  method: 'POST',
  body: JSON.stringify({
    assistant_id: 'agent_name',
    input: { messages: [...] },
    // ✅ 关键：放入 configurable
    config: {
      configurable: {
        analysis_id: "idx_123",
        user_id: "usr_456"
      }
    }
  })
})
```

#### 2. 后端接收 (Backend Access: Tool & Node)
LangGraph 会自动将 API 请求中的 `config` 注入到 **Tool** 和 **Node** 的执行上下文中。

> **注意**: 凡是被 `Runnable` 接口调用或包装的函数（包括 Tool 和 Node），只要签名中包含 `config` 参数，运行时都会自动注入配置。

*   **定义**: 函数必须包含 `config: RunnableConfig` 参数。
*   **读取**: 直接从 `config["configurable"]` 获取。

**示例 1: Tool (工具)**
```python
from langchain_core.runnables import RunnableConfig

@tool
def my_tool(arg1: str, config: RunnableConfig) -> str:
    # ✅ 正确：从 config 读取上下文
    analysis_id = config.get("configurable", {}).get("analysis_id")
    # ...
```

**示例 2: Node (普通节点函数)**
```python
def my_node(state: AgentState, config: RunnableConfig) -> dict:
    # ✅ Node 同样可以接收 config
    user_id = config.get("configurable", {}).get("user_id")
    return {"status": "processing", "user": user_id}
```

#### 3. Middleware 获取 (Middleware Access)
在 LangGraph Runtime 中，Middleware 的所有 Hook 方法（如 `awrap_tool_call`, `abefore_agent`, `aafter_agent`）都可以通过 `runtime.context` 访问这些值。

*   **场景**: 在 `awrap_tool_call`（拦截工具）或 `aafter_agent`（结果处理）中访问全局配置。
*   **方式**: 优先检查 `runtime.context`。

```python
class MyMiddleware(AgentMiddleware):
    # 示例 1: 拦截工具调用
    async def awrap_tool_call(self, request, handler):
        analysis_id = self._get_config_value(request.runtime, "analysis_id")
        return await handler(request)

    # 示例 2: 处理 Agent 结果
    async def aafter_agent(self, state, runtime, result):
        analysis_id = self._get_config_value(runtime, "analysis_id")
        # 使用 analysis_id 读取文件或处理结果...
        return result
        
    def _get_config_value(self, runtime, key):
        # 1. 尝试从 runtime.context 获取 (LangGraph CLI)
        if hasattr(runtime, "context") and isinstance(runtime.context, dict):
            val = runtime.context.get(key)
            if val: return val
            
        # 2. 回退到 runtime.config
        config = getattr(runtime, "config", {})
        return config.get("configurable", {}).get(key)
```

## 5. 多模态文件流处理 (Multimodal File Flow)

处理用户上传文件（PDF/Image/Excel）的核心挑战是：**LLM 上下文窗口限制与 Token 成本**。直接将文件 Base64 放入 Prompt 是不可持续的。

### 核心策略：Payload Offloading (负载卸载)

使用 Middleware 实现 **"拦截 -> 落盘 -> 引用"** 的转换机制：

1.  **拦截 (Intercept)**: 前端协议将文件封装为自定义的 `FileBlock`（包含 Base64 数据）。
2.  **落盘 (Offload)**: Middleware 识别 `type="file"`，将 Base64 解码并写入共享文件系统 (`/data/workspace/uploads/`)。
3.  **引用 (Reference)**: 将原来的 File Block **替换**为 Text Block，仅保留文件路径。

### 转换示例
**输入消息 (前端发送)**:
```json
[
  {"type": "text", "text": "分析这个文档"},
  {"type": "file", "data": "JVBERi0xLjQK...", "name": "report.pdf"}
]
```

**输出消息 (LLM 看到)**:
```text
分析这个文档
[System: 用户上传了文件: /data/workspace/uploads/report.pdf]
```

> **优势**: 
> 1. LLM 仅看到路径，零 Token 消耗。
> 2. 下游工具（如 Python/SQL Agent）可以直接读取本地文件进行处理。

## 6. 中间件机制 (Middleware)

充分利用 Middleware 处理切面逻辑，保持业务代码纯净：

*   **Result Bubbling**: (`ArticleContentMiddleware`, `StructuredOutputToTextMiddleware`) 将 Sub-Agent 的复杂执行结果（如生成的长文、图表数据）提取并"冒泡"给 Main Agent 或前端，防止被 LLM 总结时丢失细节。
*   **Logging & Debug**: (`ThinkingLoggerMiddleware`) 记录思维链和工具调用参数，便于调试。
*   **Validation**: (`IllustratorValidationMiddleware`) 在 Agent 返回结果前拦截并校验（如检查生成图片路径是否存在），自动修复错误。
*   **Artifact Injection**: (`FileContentInjectionMiddleware`) 拦截 Sub-Agent 的 Tool 返回，从文件系统读取生成的内容（如 `chart.json`, `report.md`），注入到 `ToolMessage.artifact` 字段。前端可直接渲染，无需 LLM 中转。

#### FileContentInjectionMiddleware 模式

当 Sub-Agent 生成文件型产物（图表、报告）时，使用此中间件将内容直接注入到消息流中：

```python
class FileContentInjectionMiddleware(AgentMiddleware):
    async def awrap_tool_call(self, request, handler):
        result = await handler(request)
        
        # 只处理 task 工具（调用 Sub-Agent）
        if request.name != "task":
            return result
            
        subagent_type = request.args.get("subagent_type")
        
        if subagent_type == "visualizer_agent":
            chart_path = f"/data/workspace/artifacts/{analysis_id}/chart.json"
            with open(chart_path, 'r') as f:
                chart_data = json.load(f)
            return ToolMessage(
                content=result.content + "\n[System: Chart artifact loaded]",
                tool_call_id=result.tool_call_id,
                artifact={"type": "chart", "data": chart_data}  # 前端直接读取
            )
        elif subagent_type == "report_agent":
            report_path = f"/data/workspace/artifacts/{analysis_id}/report.md"
            with open(report_path, 'r') as f:
                report_content = f.read()
            return ToolMessage(
                content=result.content + "\n[System: Report artifact loaded]",
                tool_call_id=result.tool_call_id,
                artifact={"type": "report", "content": report_content}
            )
        return result
```

**前端处理**:
```javascript
if (msg.type === 'tool' && msg.artifact) {
    if (msg.artifact.type === 'chart') {
        chartConfig.value = msg.artifact.data
        renderChart()
    } else if (msg.artifact.type === 'report') {
        analysisResult.value = msg.artifact.content
    }
}
```

> **优势**: LLM 无需输出大段 JSON/Markdown，只需生成文件即可。Middleware 负责读取和分发，前端直接渲染结构化数据。

### Middleware 同步/异步 Hook
LangChain AgentMiddleware 同时支持同步和异步版本的 hook 方法：

| 同步方法 | 异步方法 |
|---------|----------|
| `before_agent` | `abefore_agent` |
| `after_agent` | `aafter_agent` |
| `wrap_tool_call` | `awrap_tool_call` |
| `wrap_model_call` | `awrap_model_call` |

**优先使用异步版本**，因为 `runtime.store` 要求使用 `aput()`/`aget()` 异步 API。


## 7. LangGraph Command 模式 (Dynamic Routing)

LangGraph 提供了两种方式来控制节点间的流程跳转：

### 传统方式：`add_conditional_edges`
```python
def check_retry(state):
    if state.get("error_feedback") and state.get("retry_count", 0) < 3:
        return "retry"
    return "continue"

graph.add_conditional_edges("execute", check_retry, {"retry": "generate", "continue": "output"})
```
**缺点**：逻辑分散在两处（节点函数 + routing 函数），不易维护。

### 推荐方式：`Command` 模式
将状态更新和流程跳转合并到节点函数内部，返回 `Command` 对象：
```python
from langgraph.types import Command
from typing import Literal

def step_execute(state: State) -> Command[Literal["generate", "output"]]:
    result = execute_code(state.get("code"))
    
    if not result.success and state.get("retry_count", 0) < 3:
        return Command(
            update={"error_feedback": result.error, "retry_count": state["retry_count"] + 1},
            goto="generate"  # 重试
        )
    
    return Command(update={"result": result.output}, goto="output")
```

### 最佳实践
1. **类型注解**：使用 `-> Command[Literal["node_a", "node_b"]]` 明确可跳转节点，IDE 和类型检查器可捕获错误。
2. **逻辑内聚**：所有判断逻辑集中在节点函数内，无需额外的 routing 函数。
3. **简化 Graph 定义**：无需 `add_conditional_edges`，Graph 构建代码更简洁。

---

## 8. Human-in-the-Loop (HITL) 集成

对于需要用户审核的关键步骤（如图表生成、报告生成），使用 `interrupt` 暂停执行并等待用户反馈。

### 后端：使用 `interrupt`
```python
from langgraph.types import interrupt

def generate_report(state):
    report = llm.generate(state["data"])
    
    # 暂停并等待用户审核
    user_decision = interrupt({
        "type": "report",
        "content": report,
        "action": "请审核报告，批准或提供修改意见"
    })
    
    if user_decision.get("type") == "reject":
        feedback = user_decision.get("message")
        # 根据反馈重新生成...
```

### 前端：处理中断
```javascript
// 监听 interrupt 事件
if (event.type === 'interrupt') {
    showReviewOverlay(event.data);
}

// 用户决策后 resume
async function handleDecision(type, message) {
    await client.runs.resume(threadId, runId, {
        decisions: [{ type, message }]
    });
}
```

### Main Agent 反馈透传
当用户拒绝后，Main Agent 必须将**用户原话反馈**包含在重新调用 Sub-Agent 的 `description` 中：
```python
# ❌ 错误：模糊描述
task(subagent_type='report_agent', description='根据用户反馈修改报告')

# ✅ 正确：包含具体反馈
task(subagent_type='report_agent', description='用户反馈：去掉数据概览章节。请根据此反馈修改报告。')
```

---

## 9. 防错与自愈 (Robustness Patterns)

### 1. Error-as-Input (错误即输入自愈)
当工具执行失败（如 Python 代码报错）时，将 stderr 作为 Input 返回给当前 Agent。
*   **ReAct 模式**: 让 LLM 在同一个 Loop 中根据错误自修正代码。
*   **Graph 模式**: 配置 `conditional_edge`，如果连续 N 次修正失败，自动路由到 `HumanFallback` 节点。

### 2. 节点内重试机制
在执行节点（如 `python_execute`、`sql_execute`）内部实现重试逻辑，结合 Command 模式使用：

```python
def step_execute(state: State) -> Command[Literal["generate", "output"]]:
    retry_count = state.get("retry_count", 0)
    
    try:
        result = execute(state["code"])
        if not result.success:
            raise ExecutionError(result.error)
        return Command(update={"result": result}, goto="output")
    
    except Exception as e:
        if retry_count < 3:  # 熔断阈值
            return Command(
                update={"retry_count": retry_count + 1, "error_feedback": str(e)},
                goto="generate"  # 回到 LLM 重新生成
            )
        else:
            # 超过重试次数，强制结束并输出错误
            return Command(
                update={"result": f"执行失败: {e}"},
                goto="output"
            )
```

**最佳实践**:
1. **熔断机制**：设置最大重试次数（通常 3 次），超过后强制结束，避免无限循环。
2. **错误反馈**：将错误信息存入 `error_feedback` 状态，LLM 可在下次生成时参考修正。

### 3. Reviewer Loop (图层级审核循环)
不要让生成节点直接连接结束。在 `Generate` 和 `End` 之间插入 `Review` 节点。
*   **Agent-Reviewer**: 引入专门的 `reviewer_agent`（配置更严格的 Prompt）对生成内容进行审核。不通过则路由回 `Generate` 重写。
*   **Human-in-the-loop**: 在任意关键节点（如生成图表后、生成报告后）使用 `interrupt` 暂停，等待用户确认或修改。

### 4. System Hints (系统旁白/导航)
在 Tool 的输出结果中动态注入 `[SYSTEM HINT]`（如 "`DO NOT FINISH, Call report_agent next`"）。
*   **作用**: 像 GPS 导航一样，在多步任务执行中即时纠正 Agent 的下一步行动，防止其在长 Context 中遗忘最终目标或过早结束。



## 10. Python 沙箱执行 (Python Sandbox Execution)

在动态执行用户/LLM 生成的 Python 代码时，需要特别注意 Python 3 的作用域规则。

### exec() 中的作用域陷阱

Python 的 `exec(code, globals, locals)` 在传入单独的 `locals` 字典时，会遇到**列表推导式作用域问题**：

> **Python 3 中，列表推导式、生成器表达式、字典推导式等都有独立的作用域**，它们只能访问 `globals`，无法访问 `exec()` 的 `locals`。

**反模式 (会导致 `NameError: name 'df' is not defined`)**:
```python
# ❌ 错误：使用单独的 locals 字典
safe_globals = {"load_dataframe": load_dataframe}
safe_locals = {}

code = '''
df = load_dataframe('result')
chart = {"series": [x for x in df.columns]}  # 列表推导式内部无法访问 df！
'''

exec(code, safe_globals, safe_locals)  # 报错！
```

**最佳实践 (只用 globals)**:
```python
# ✅ 正确：所有变量存入 globals，不使用单独的 locals
safe_globals = {"load_dataframe": load_dataframe}

code = '''
df = load_dataframe('result')
chart = {"series": [x for x in df.columns]}  # df 在 globals 中，推导式可访问
'''

exec(code, safe_globals)  # 成功！
```

### 关键要点
1.  **只传 `globals`**，不要传单独的 `locals` 参数
2.  **用户定义的变量**（如 `df`）会存入 `globals` 字典中
3.  这是 Python 3 的语言特性，与 LangChain 无关

## 11. 技能模式 (Skills Pattern)

当一个 Agent 需要处理多种类型的任务（如通用分析、统计分析、机器学习）时，推荐使用 **Skills 模式** 替代多个独立 Agent。

### 核心设计
```python
# skills/registry.py
SKILLS_REGISTRY = {
    "general": "通用数据处理指令...",
    "statistics": "统计分析专用指令（包含 scipy/statsmodels 示例）...",
    "ml": "机器学习指令（包含 sklearn pipeline 示例）...",
}
```

### 调用方式
Main Agent 通过标签指定技能：
```
[skill=statistics] 对 result DataFrame 执行回归分析
```

Python Agent 的 `step2_llm_generate_code` 动态解析标签，将对应的技能指令注入到 System Prompt 中。

### 优势
| 对比项 | 多 Agent 模式 | Skills 模式 |
| :--- | :--- | :--- |
| 上下文共享 | 需显式传递 DataFrame 路径 | 同一 Python 环境，直接复用 `df` 变量 |
| Graph 复杂度 | 节点多，路由复杂 | 单一 Agent，内部切换 Prompt |
| 扩展性 | 新增 Agent 需改图 | 仅需更新 `SKILLS_REGISTRY` |

## 12. 总结架构图

```mermaid
flowchart TB
    U[用户输入]

    subgraph PRE[输入阶段]
        MI[Middleware（预处理）]
    end

    subgraph CORE[编排阶段]
        ORC[Main Agent（编排器）]
    end

    subgraph P1[模式 1：LLM 驱动 Sub-Agent]
        SA1[Sub-Agent（ReAct）]
        T[Tools]
        SA1 -->|Call| T
        T -->|Result| SA1
    end

    subgraph P2[模式 2：StateGraph + Skills]
        SA2[Sub-Agent（StateGraph）]
        SK[Skills Registry]
        LLM[LLM 生成]
        SA2 --> SK --> LLM
    end

    subgraph POST[输出阶段]
        MO[Middleware（后处理）]
        OUT[输出]
    end

    U --> MI --> ORC
    ORC --> SA1 --> MO
    ORC --> SA2 --> MO
    MO --> OUT
```

## 13. 全栈数据流最佳实践 (Full-Stack Data Flow)

在 LangGraph 流式传输场景下，确保大数据量（如图表配置）的完整性和前端解析的稳定性至关重要。以下是针对 LangChain 1.0/LangGraph 的关键优化模式。

### 后端序列化 (Backend Serialization)
LangGraph 在 `stream_mode="values"` 时，默认会将 Pydantic 状态对象转换为字符串流式传输。如果未做处理，输出的是 Python 对象的 `repr()`（如 `{'key': True}`），这会导致前端 JSON 解析失败。

**最佳实践**：
在 Pydantic 模型（如 `MainAgentOutput`）中重写 `__str__` 方法，强制返回标准 JSON。

```python
class MainAgentOutput(BaseModel):
    # ... fields ...

    def __str__(self):
        """Override string representation to return valid JSON.
        Ensures LangGraph streams valid JSON instead of Python object repr.
        """
        try:
            return self.model_dump_json(exclude_none=True)
        except Exception:
            return super().__str__()
```

### 前端流式解析 (Frontend SSE Parsing)
网络传输层会将大数据包（如几 KB 的 ECharts 配置）拆分为多个 TCP 包（Chunks）。前端不应假设每个 SSE 事件 (`data: ...`) 都应在单个 Chunk 中结束。

**反模式 (Naive Splitting)**:
```javascript
// ❌ 错误：假设 chunk.split('\n') 能完美分割 lines
const lines = chunk.split('\n') 
for (const line of lines) JSON.parse(line) // 如果 JSON 被截断则报错
```

**最佳实践 (Buffer Mechanism)**:
前端必须维护一个 Buffer 来拼接跨 Chunk 的数据。

```javascript
// ✅ 正确：使用 Buffer 拼接
let buffer = ''
while (reader) {
  const { value } = await reader.read()
  buffer += decoder.decode(value, { stream: true })
  
  const lines = buffer.split('\n')
  // 保留最后一行（可能是半截数据），留待下一次拼接
  buffer = lines.pop() || '' 
  
  for (const line of lines) {
    if (line.startsWith('data: ')) process(line)
  }
}
```

### 消息过滤 (Message Filtering)
虽然 Main Agent 被强制要求返回结构化输出（JSON），但在使用 Middleware 模式时，LangGraph 仍会广播两条语义重复的消息：
1.  **原始节点消息**: `MainAgent` 节点的直接输出（标准 JSON）。
2.  **Middleware 消息**: 经过 Middleware 再次封装的协议消息（如添加 `DATA_RESULT:` 前缀）。

**最佳实践**: 
前端应通过 `msg.name` 识别并**过滤掉原始节点消息**，只消费 Middleware 封装后的协议消息。
*   **原因**: 避免界面重复渲染同一份数据。
*   **优势**: Middleware 消息通常包含了从 Context 提取的额外元数据（如 `analysis_id`），且格式统一（Text/Markdown Wrapper），比纯 JSON 更适合直接对接聊天界面渲染器。

## 14. LangChain 核心消息对象详解 (LangChain Message Objects)

LangChain 定义了一套标准的消息协议。随着多模态和 Tool Calling 的发展，这些消息对象的结构变得灵活多态。正确解析它们是前端展示和后端逻辑的基础。

### 1. AIMessage (模型输出)

代表 LLM 的响应。继承自 `BaseMessage`。

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| **`content`** | `str \| List[Union[str, Dict]]` | **必填**。主要文本内容。多模态场景下为 Block 列表（Text/Image）。当 `tool_calls` 存在时可能为空。 |
| **`tool_calls`** | `List[ToolCall]` | **可选**。模型生成的工具调用请求列表。每个 `ToolCall` 包含 `name` (工具名), `args` (参数字典), `id` (唯一ID)。 |
| **`usage_metadata`** | `UsageMetadata` | **可选**。Token 消耗统计（`input_tokens`, `output_tokens`, `total_tokens`）。(LangChain 0.1.17+) |
| **`response_metadata`** | `Dict` | **可选**。底层模型提供商的原始响应元数据（如 `finish_reason`, `logprobs`）。 |
| **`invalid_tool_calls`** | `List[InvalidToolCall]` | **可选**。模型生成了无法解析为合法 ToolCall 的内容（如 JSON 格式错误），用于容错处理。 |
| **`name`** | `str` | **可选**。发送者名称（通常为空，但在多 Agent 场景可用于标记身份）。 |

### 2. ToolMessage (工具结果)

代表工具执行后的返回结果。必须紧跟在发起调用的 `AIMessage` 之后。

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| **`content`** | `str \| List` | **必填**。工具执行结果的**字符串表示**。这是 LLM 唯一能看到的内容。务必简洁，避免 Context 溢出。 |
| **`tool_call_id`** | `str` | **必填**。对应 `AIMessage.tool_calls[i].id`，用于将结果与请求匹配。 |
| **`artifact`** | `Any` | **可选** (LangChain 0.2+)。**原始执行结果**。可以存储 DataFrame、二进制图像、Pydantic 对象等。**LLM 看不到此字段**，专供后续 ToolNode 或 Middleware 使用。 |
| **`status`** | `'success' \| 'error'` | **可选**。工具执行状态。用于在 Frontend 区分展示或 Graph 路由判断（如 Error 时重试）。 |
| **`name`** | `str` | **可选**。工具名称。 |

### 3. 解析策略表
| 场景 | 关键字段 | 处理逻辑 |
| :--- | :--- | :--- |
| **普通对话** | `AIMessage.content` | 直接显示文本。注意处理流式输出中的空字符串。 |
| **工具调用** | `AIMessage.tool_calls` | 渲染为 "正在调用工具: {name}..."。应遍历列表处理并行调用。 |
| **工具结果** | `ToolMessage.content` | 渲染为工具执行摘要。 |
| **多模态展示** | `ToolMessage.artifact` | **优先使用**。由 Middleware 提取并转换为前端特定格式（如 `DATA_RESULT`）。不要试图从 content 解析复杂数据。 |
| **错误处理** | `AIMessage.invalid_tool_calls` | 如果存在，应提示用户模型意图识别失败或自动触发重试机制。 |

> **版本提示**: 本说明基于 LangChain 1.x / `langchain-core` 0.2+ 规范。老版本（0.0.x）可能缺少 `artifact`, `status`, `usage_metadata` 等字段。

### 4. Content Block 结构与访问 (Vendor Abstraction)

LangChain 为了屏蔽底层厂商（OpenAI, Anthropic 等）的格式差异，定义了一套**标准 Content Block**。

#### 标准 Block 类型

| Block 类型 | `type` 值 | 关键字段 | 说明 | 厂商适配 (LangChain 自动处理) |
| :--- | :--- | :--- | :--- | :--- |
| **文本块** | `"text"` | `text` | 纯文本内容。 | 基础通用。 |
| **思维链** | `"reasoning"` | `reasoning` | 模型的推理过程（CoT）。 | **LangChain 标准**。DeepSeek/Anthropic 的输出正逐渐标准化为此格式。 |
| **图片块** | `"image"` | `url` / `base64` | 图片资源。 | **OpenAI** 转为 `image_url` 对象；**Anthropic** 转为 `source` 对象。 |
| **工具调用** | `"tool_use"` | `id`, `name`, `input` | 模型发起的工具调用。 | **OpenAI** 转为 `function_call`；**Anthropic** 转为 `tool_use`。 |
| **工具结果** | `"tool_result"` | `tool_use_id`, `content` | 工具执行结果。 | —— |

> **注意**：`.content_blocks` 属性只负责解析 `message.content` 字段。如果底层模型接口（Provider）尚未适配标准，将思维链放在了 `additional_kwargs` 而非 `content` 中，那么 `.content_blocks` **不会包含**思维链数据。因此需要下文的双重检查策略。

#### 构造消息（推荐使用标准格式）
```python
# ✅ 推荐: 使用 LangChain 标准格式 (跨模型通用)
msg = HumanMessage(content=[
    {"type": "text", "text": "分析这张图片"},
    {"type": "image", "url": "http://example.com/img.jpg"}
])

# ❌ 不推荐: 使用厂商原生格式 (绑定特定模型)
msg = HumanMessage(content=[
    {"type": "text", "text": "分析这张图片"},
    {"type": "image_url", "image_url": {"url": "..."}}  # OpenAI 特定格式
])
```

#### 访问消息内容（使用 `.content_blocks`）

LangChain 1.x (`langchain-core` 1.2+) 引入了 **`.content_blocks`** 属性，解决了 `content` 字段类型不确定（`str | List`）的问题：

```python
# ❌ 繁琐：手动判断 content 类型
content = msg.content
if isinstance(content, str):
    text = content
elif isinstance(content, list):
    text = "".join(b.get("text", "") for b in content if b.get("type") == "text")

# ✅ 简洁：使用 .content_blocks，始终返回 List
def extract_text_from_message(message: BaseMessage) -> str:
    blocks = message.content_blocks  # 始终是 List[ContentBlock]
    return "".join(
        block.get("text", "") 
        for block in blocks 
        if isinstance(block, dict) and block.get("type") == "text"
    )

# ✅ 提取思维链（同时兼容标准 Block 和 additional_kwargs）
def extract_reasoning(message: BaseMessage) -> str:
    # 1. 优先尝试从标准 Block 提取
    blocks = message.content_blocks
    from_blocks = "".join(
        block.get("reasoning", "") 
        for block in blocks 
        if isinstance(block, dict) and block.get("type") == "reasoning"
    )
    if from_blocks: return from_blocks
    
    # 2. 回退到 additional_kwargs (兼容旧版 DeepSeek/vLLM)
    return message.additional_kwargs.get("reasoning_content", "")
```

> **提示**: `.content_blocks` 会自动将 `str` 类型的 `content` 包装为 `[{"type": "text", "text": content}]`，确保统一的访问接口。
