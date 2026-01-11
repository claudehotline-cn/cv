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

## 2. 状态管理与上下文传递 (State & Context)

### 全局唯一标识 (Analysis/Article ID)
*   **必须性**: 在多 Agent 协作中，必须有一个全局 ID (`analysis_id` 或 `article_id`) 贯穿始终，用于关联文件、数据和上下文。
*   **传递机制**:
    *   **Prompt 显式传递**: Main Agent 在调用 Sub-Agent 时，必须在 `description` 中包含 ID（例如 `description="[analysis_id=xyz] 查询..."`）。
    *   **Middleware 隐式注入**: 使用 Middleware (`AnalysisIDMiddleware`) 自动从上下文提取 ID 并注入到 Tool 的参数中，防止 LLM 忘记传参。

### 共享存储 (Shared Store)
*   使用 `InMemoryStore` 或持久化 Store 在不同 Agent 线程间共享数据（如全局 ID）。

## 3. 提示词工程 (Prompt Engineering)

### 严格的流程控制
*   在 `MAIN_AGENT_PROMPT` 中明确定义标准工作流（SOP）。
*   使用 **"严禁..."**, **"必须..."** 等强硬措辞约束行为。
*   明确“完成条件”，例如“只有收到 `report_agent` 的 Markdown 输出才算结束”。

### 结构化输入输出
*   Sub-Agent 的 System Prompt 中应包含详细的参数说明和示例。
*   对于需要精确格式的输出（如 JSON），使用 Pydantic Model (`response_format`) 结合 Middleware 强制格式化。

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

## 5. 多模态输入与 Content Block 处理 (Content Blocks)

现代 Agent 系统通常需要处理多模态输入（如文件上传）。消息内容不再是单纯的字符串，而是 **Content Block 列表**。

### 消息结构
前端上传的文件通常以 Block 形式封装在 `HumanMessage` 中：
```python
# HumanMessage.content 示例
[
    {"type": "text", "text": "分析这个文档"},
    {
        "type": "file", 
        "mimeType": "application/pdf", 
        "data": "base64_encoded_string...",
        "metadata": {"filename": "report.pdf"}
    }
]
```

### 处理策略
不要让 Agent 直接处理巨大的 Base64 字符串。应使用 Middleware 在 `before_agent` 阶段进行预处理：

1.  **拦截 (Intercept)**: 检查 `message.content` 是否为 List 类型。
2.  **提取 (Extract)**: 识别 `type="file"` 的 Block，解码 Base64 数据并保存到共享工作区 (`/data/workspace/uploads/`)。
3.  **替换 (Replace)**: 将 File Block 替换或追加为包含**文件绝对路径**的 Text Block。
    *   *Before*: `[FileBlock(data=...)]`
    *   *After*: `[TextBlock(text="用户上传了文件: /data/workspace/uploads/report.pdf")]`

> **最佳实践**: 参考 `PDFAttachmentMiddleware` 的实现，将多模态数据流转换为 LLM 易于理解的文本路径引用，实现**"文件输入 -> 路径引用 -> 工具读取"**的闭环。

## 6. 中间件机制 (Middleware)

充分利用 Middleware 处理切面逻辑，保持业务代码纯净：

*   **Result Bubbling**: (`ArticleContentMiddleware`, `StructuredOutputToTextMiddleware`) 将 Sub-Agent 的复杂执行结果（如生成的长文、图表数据）提取并"冒泡"给 Main Agent 或前端，防止被 LLM 总结时丢失细节。
*   **Logging & Debug**: (`ThinkingLoggerMiddleware`) 记录思维链和工具调用参数，便于调试。
*   **Validation**: (`IllustratorValidationMiddleware`) 在 Agent 返回结果前拦截并校验（如检查生成图片路径是否存在），自动修复错误。

## 6. 防错与自愈 (Robustness)

*   **Reviewer Loop**: 引入 `reviewer_agent` 对生成内容（代码、文章）进行审核。如果审核不通过，打回重写。
*   **Programmatic Fallback**: 在 `StateGraph` 中，如果 LLM 生成代码失败，可以捕获异常并返回错误信息，或者回退到安全模式。
*   **System Hints**: 在工具输出中注入 `[SYSTEM HINT]`（如 "`DO NOT FINISH, Call report_agent next`"），在上下文中即时纠正 Main Agent 的行为。

## 7. 文件系统与工作区 (Filesystem Backend)

DeepAgent 使用 `Backend` 抽象来管理文件操作。正确配置 Backend 对于安全性和数据隔离至关重要。

### 推荐配置
使用 `CompositeBackend` 组合文件系统和内存存储：

```python
backend=lambda rt: CompositeBackend(
    default=FilesystemBackend(
        root_dir="/data/workspace",  # 此为容器内绝对路径
        virtual_mode=True            # 开启沙箱模式，RESTRICT 文件操作在此目录及其子目录内
    ),
    routes={
        "/_shared/": StoreBackend(rt),  # 将特定路径路由到内存/Redis Store，用于跨 Agent 高速共享
    }
)
```

### 最佳实践
1.  **开启 Virtual Mode**: 务必设置 `virtual_mode=True`，防止 Agent 越权访问系统敏感文件（如 `/etc/passwd`）。
2.  **统一工作区根目录**: 所有 Tool 的操作路径应基于此根目录。
3.  **Artifact 目录结构**: 建议按 ID 隔离 Artifacts，例如 `/data/workspace/artifacts/{analysis_id}/`，避免不同任务间文件冲突。

## 8. 技能模式 (Skills Pattern)

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

## 9. 总结架构图

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

## 10. 全栈数据流最佳实践 (Full-Stack Data Flow)

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

## 11. LangChain 核心消息对象详解 (LangChain Message Objects)

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

### 4. 标准 Content Block 结构 (Vendor Abstraction)
LangChain 为了屏蔽底层厂商（OpenAI, Anthropic 等）的格式差异，定义了一套**标准 Content Block**。推荐在业务代码中**优先构造标准 Block**，由 LangChain 自动转换为厂商特定格式。

前面3点描述的是消息对象（Container）及其顶层属性（如 `tool_calls`）。本节描述的是 **`content` 字段** 的标准内部结构。它是 `AIMessage.content` 或 `HumanMessage.content` 的具体填充物。

| Block 类型 | `type` 值 | 关键字段 | 说明 | 厂商适配 (LangChain 自动处理) |
| :--- | :--- | :--- | :--- | :--- |
| **文本块** | `"text"` | `text` | 纯文本内容。 | 基础通用。 |
| **图片块** | `"image"` | `url` / `base64` | 图片资源。 | **OpenAI** 转为 `image_url` 对象；**Anthropic** 转为 `source` 对象。 |
| **工具调用** | `"tool_use"` | `id`, `name`, `input` | 模型发起的工具调用。 | **OpenAI** 转为 `function_call`；**Anthropic** 转为 `tool_use`。 |
| **工具结果** | `"tool_result"` | `tool_use_id`, `content` | 工具执行结果。 | —— |

**最佳实践示例**:
```python
# ✅ 推荐: 使用 LangChain 标准格式 (跨模型通用)
msg = HumanMessage(content=[
    {"type": "text", "text": "分析这张图片"},
    {"type": "image", "url": "http://example.com/img.jpg"}
])

# ❌ 不推荐: 使用厂商原生格式 (绑定特定模型, e.g. OpenAI)
msg = HumanMessage(content=[
    {"type": "text", "text": "分析这张图片"},
    {"type": "image_url", "image_url": {"url": "..."}} 
])
```
