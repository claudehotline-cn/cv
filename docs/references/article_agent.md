好，我们就把你引用的这段 **Planner / Researcher / Writer / Illustrator 多子 Agent deep agent 思路**，落地成一个**基于 LangGraph 的多 Agent 工作流设计方案**，并且满足你现在这些前提：

- LangChain 1.0
- LangGraph + langgraph CLI + Docker
- 模型用 Ollama
- **只用原图，不生成新图**（Illustrator 角色改成“图片策展/选图”而不是生成）
- 前端是 Agent Chat UI

我分三层说：**角色职责设计 → LangGraph 状态 & 节点设计 → 一个精简的代码骨架示例**。

------

## 一、四个子 Agent 的职责重定义（适配“只用原图”）

参考 LangGraph 官方多 Agent 思路，每个 Agent 就是一个节点，有自己独立的 prompt + 工具[LangChain Blog+2CWAN+2](https://blog.langchain.com/langgraph-multi-agent-workflows/?utm_source=chatgpt.com)。

### 1. Planner 子 Agent（规划 / 调度）

**定位**：高层 orchestrator，类似“项目经理”。

- 输入：
  - 用户指令（用途/读者/语气）
  - 链接列表、文件列表
- 输出写回 State：
  - `outline`：文章大纲（H1/H2/H3）
  - `plan`：需要哪些信息源、是否需要多轮摘要/对比
  - `sections_to_research`：每个小节需要回答的问题列表
  - 标记是否需要额外补充外部知识（非必须）

**工具**：通常不直接调工具，只是规划；必要时可以调用一些轻量工具（比如检查 link 可用性），但可以先省略。

------

### 2. Researcher 子 Agent（检索 / 摘要）

**定位**：资料员 + 分析师，核心是“从链接/文件中提取和压缩信息”。

- 输入：
  - `outline` + `sections_to_research`
  - `urls`、`file_paths`
- 输出写回 State：
  - `source_summaries`: 按 source（每个链接/文件）生成摘要
  - `section_notes`: 按小节聚合的笔记（多来源归纳）
  - `image_metadata`:
    - 网页图片 URL
    - PDF/DOCX/PPTX 提取出来的原图在 `/data/articles/assets/{article_id}/...` 的路径、来源位置（第几页/第几张）

**工具**（挂在 Researcher 这个节点上）：

- `fetch_url_with_images`：抓正文 + 原图 URL（我们前面已经设计过）[LangChain 文档+1](https://docs.langchain.com/oss/python/langgraph/graph-api?utm_source=chatgpt.com)
- `load_uploaded_file_text`：读取 pdf/docx/md/txt 文本
- `extract_images_from_pdf / docx / pptx`：只复制原图，不生成新图

> 这个子 Agent 会大量调用工具，是整个 deep agent 信息流的入口。

------

### 3. Writer 子 Agent（写作 / 结构化输出）

**定位**：写手，把 `section_notes + outline` 变成高质量 Markdown 文章。

- 输入：
  - `outline`
  - `section_notes`（Researcher 整理好的每节要点）
  - `image_metadata`（每个 section 对应可用的原始图片列表）
- 输出写回 State：
  - `draft_markdown_sections`：按 section 存储的 Markdown 片段
  - 或 `draft_markdown`：整篇初稿
  - 对每个图片给出建议的说明文字（alt/caption），但不生成图片。

**工具**：
 通常不再调外部工具，只用 LLM 能力写 Markdown；如有需要可以调一些“辅助工具”（例如格式检查），可后续再加。

------

### 4. Illustrator 子 Agent（图片策展 / 选图，不生成）

这一步在你的场景里应该叫 **ImageCurator / Illustrator（不生成，只选图）** 更准确：

**定位**：把 Researcher 抽取的图片 + Writer 写好的内容结合起来，决定每节用哪几张图，以及 alt 文案和引用格式。

- 输入：
  - `draft_markdown_sections` 或 `draft_markdown`
  - `image_metadata`（来源、路径、关联 section 的标签）
- 输出写回 State：
  - `final_markdown`：在合适位置插入 `![说明](图片路径或 URL)` 之后的版本
  - 或给出一个结构化 `image_plan`，再由 Assembler 节点进行真正插入。

**硬性约束**：

- 只能用 `image_metadata` 里已有的图片路径或网页原始图片 URL。
- 不允许调用任何 image generation 工具。

> 这里你仍然可以用 LLM，让它“思考”哪张图放哪儿、说明怎么写，但它不接触任何会生成图片的工具。

------

### 5. Assembler 子 Agent（组装 / 导出）

**定位**：终结者，把内容与下载链接打包输出。

- 输入：
  - `final_markdown`（或 Writer + Illustrator 组合产出的 Markdown）
  - `article_id`、`title`
- 输出写回 State：
  - `download_info`：`md_url` + `assets_base_url` + 其他 meta
- 工具：
  - `export_markdown`：把 Markdown 落到 `/data/articles`，返回下载链接（我们前面写过）。

------

## 二、LangGraph 状态 & 节点结构设计

参考 LangGraph Graph API：State 是一个共享快照；节点是函数；边控制流程[LangChain 文档+2LangChain 文档+2](https://docs.langchain.com/oss/python/langgraph/graph-api?utm_source=chatgpt.com)。

### 2.1 State 结构（TypedDict / Pydantic）

可以这样（示意）：

```
from typing import TypedDict, List, Dict, Any, Optional

class ContentAgentState(TypedDict, total=False):
    # 用户输入 & 元数据
    instruction: str
    urls: List[str]
    file_paths: List[str]
    article_id: str
    title: Optional[str]

    # Planner 输出
    outline: List[Dict[str, Any]]          # 每个 item: {id, level, title, parent_id,...}
    sections_to_research: List[Dict[str, Any]]

    # Researcher 输出
    source_summaries: Dict[str, str]       # source_id -> summary text
    section_notes: Dict[str, str]          # section_id -> compiled notes
    image_metadata: Dict[str, List[Dict]]  # section_id -> [{path/url, source, desc,...}]

    # Writer 输出
    draft_markdown_sections: Dict[str, str]
    draft_markdown: Optional[str]

    # Illustrator 输出
    final_markdown: Optional[str]

    # Assembler 输出
    download_info: Optional[Dict[str, str]]

    # 控制流 / 日志
    error: Optional[str]
    step_history: List[str]
```

> 这样每个节点都只关心自己读/写的字段，LangGraph 会负责 merge state。

------

### 2.2 节点拓扑：planner → researcher → writer ↔ illustrator → assembler

根据官方的 Multi-Agent Workflows 思路，一个典型拓扑就是多个 “Agent node” + 一个路由逻辑，你这里可以用一条主路径 + 若干条件回跳[LangChain Blog+2CWAN+2](https://blog.langchain.com/langgraph-multi-agent-workflows/?utm_source=chatgpt.com)：

- `START → planner`
- `planner → researcher`
- `researcher → writer`
- `writer → illustrator`
- `illustrator → assembler`
- `assembler → END`

高级一点，可以加：

- 如果 `researcher` 发现信息不足 → 写个 flag，在 routing 函数里再回到 `researcher`（例如再拉一次网页 / 切换其它文档等）
- 如果 `writer` 写完自检不满意 → 回到 `writer` 自我重写一轮
- 如果 `illustrator` 找不到合适图片 → 跳过插图，直接 assembler

------

## 三、一个精简的 LangGraph 代码骨架（多节点版）

这部分是**概念示例代码**，你可以在现有项目里改造；重点在结构，而不是每个工具的细节。语法参考了 LangGraph v1 的 StateGraph 用法[LangChain 文档+2LangChain 文档+2](https://docs.langchain.com/oss/python/langgraph/graph-api?utm_source=chatgpt.com)。

> 假设你已经有 `ChatOllama`、`fetch_url_with_images` 等工具实现（和我们前面方案一致）。

### 3.1 子 Agent 封装函数

先做个 helper：为每个角色创建一个“小 Agent”，每个 Agent 有定制的 system prompt + tools 列表。这种模式跟官方多 Agent RAG 示例很像[Qiita+2LangChain 文档+2](https://qiita.com/ksonoda/items/92a224e3f56255182140?utm_source=chatgpt.com)。

```
# content_agent/sub_agents.py
import os
from typing import Dict, Any
from langchain_ollama import ChatOllama
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from .tools_text import fetch_url_with_images, load_uploaded_file_text
from .tools_images import (
    extract_images_from_pdf,
    extract_images_from_docx,
    extract_images_from_pptx,
)
from .tools_export import export_markdown

def build_llm():
    return ChatOllama(
        model=os.getenv("OLLAMA_MODEL", "qwen2.5:14b"),
        temperature=0.3,
    )

def planner_agent():
    llm = build_llm()
    system_prompt = """
你是 Planner 子 Agent，负责：
- 理解用户目标、受众、风格要求。
- 根据用户提供的链接和文件，规划文章的大纲（outline）。
- 标记每个小节需要研究的关键问题（sections_to_research）。

不要直接写长文，只输出结构化的大纲和研究计划。
""".strip()
    tools = []  # 一般不需要调工具
    return create_agent(llm=llm, tools=tools, system_prompt=system_prompt)

def researcher_agent():
    llm = build_llm()
    system_prompt = """
你是 Researcher 子 Agent，负责：
- 使用工具从链接和文件中提取文本和原始图片。
- 根据 Planner 给定的 sections_to_research，对每个小节做摘要和信息归纳。
- 构造 section_notes 和 image_metadata，供 Writer 与 Illustrator 使用。
""".strip()
    tools = [
        fetch_url_with_images,
        load_uploaded_file_text,
        extract_images_from_pdf,
        extract_images_from_docx,
        extract_images_from_pptx,
    ]
    return create_agent(llm=llm, tools=tools, system_prompt=system_prompt)

def writer_agent():
    llm = build_llm()
    system_prompt = """
你是 Writer 子 Agent，负责：
- 根据 outline 和 section_notes 写出结构清晰的 Markdown 文章。
- 为每个小节预留插图位置，并参考 image_metadata 说明可能适用的图片。
- 只写 Markdown，不做文件保存。
""".strip()
    tools = []
    return create_agent(llm=llm, tools=tools, system_prompt=system_prompt)

def illustrator_agent():
    llm = build_llm()
    system_prompt = """
你是 Illustrator(图片策展) 子 Agent，负责：
- 只使用 Researcher 提取的原图（image_metadata），为 Writer 的草稿选择合适图片。
- 在 Markdown 中插入 `![说明](图片路径或URL)`。
- 不调用任何图像生成工具，不虚构图片。
""".strip()
    tools = []  # 不接任何 image generation 工具
    return create_agent(llm=llm, tools=tools, system_prompt=system_prompt)

def assembler_agent():
    llm = build_llm()
    system_prompt = """
你是 Assembler 子 Agent，负责：
- 接收最终 Markdown（包含图片引用）。
- 调用工具 export_markdown 保存文件，获取下载链接。
- 输出：简要说明 + 下载链接信息。
""".strip()
    tools = [export_markdown]
    return create_agent(llm=llm, tools=tools, system_prompt=system_prompt)
```

------

### 3.2 用 StateGraph 串成 Deep Agent

`content_agent/deep_agent_graph.py`（你可以把它取代之前的单 graph 方案，并在 `langgraph.json` 里指向这里的 graph）。

```
from typing import TypedDict, List, Dict, Any
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from .sub_agents import (
    planner_agent,
    researcher_agent,
    writer_agent,
    illustrator_agent,
    assembler_agent,
)

class ContentState(TypedDict, total=False):
    instruction: str
    urls: List[str]
    file_paths: List[str]
    article_id: str
    title: str

    outline: Any
    sections_to_research: Any

    source_summaries: Any
    section_notes: Any
    image_metadata: Any

    draft_markdown: str
    final_markdown: str

    download_info: Dict[str, str]
    messages: List[Any]  # 如果你想保留 messages 给子agent看

# 每个节点都是一个“小 agent graph”的单步调用
planner = planner_agent()
researcher = researcher_agent()
writer = writer_agent()
illustrator = illustrator_agent()
assembler = assembler_agent()

def planner_node(state: ContentState) -> ContentState:
    # 把当前 state 压缩成一条 prompt 传给 planner
    prompt = f"""
用户目标：{state.get('instruction')}
可用链接：{state.get('urls', [])}
可用文件：{state.get('file_paths', [])}

请输出：
1）文章大纲 outline（JSON 格式）
2）每个小节的研究问题列表 sections_to_research（JSON 格式）
"""
    result = planner.invoke({"input": prompt})
    # 这里简单起见，把模型输出当成字符串，你可在 prompt 中要求它输出 JSON，再 parse
    # 下同
    return {
        **state,
        "outline": result["output"],
        "sections_to_research": "...TODO parse...",
    }

def researcher_node(state: ContentState) -> ContentState:
    prompt = f"""
这是 Planner 给出的文章大纲与研究问题：
{state.get('outline')}
{state.get('sections_to_research')}

请使用可用的工具，从链接和文件中收集信息和原始图片，
然后输出：
- source_summaries
- section_notes
- image_metadata
"""
    result = researcher.invoke({"input": prompt})
    return {
        **state,
        "source_summaries": "...",
        "section_notes": "...",
        "image_metadata": "...",
    }

def writer_node_fn(state: ContentState) -> ContentState:
    prompt = f"""
大纲：
{state.get('outline')}

每节要点：
{state.get('section_notes')}

图片信息（只用来决定插图位置和说明，不要生成图片）：
{state.get('image_metadata')}

请写出整篇 Markdown 初稿（草稿），并在适当位置预留图片引用位置。
"""
    result = writer.invoke({"input": prompt})
    return {
        **state,
        "draft_markdown": result["output"],
    }

def illustrator_node_fn(state: ContentState) -> ContentState:
    prompt = f"""
以下是 Writer 写出的 Markdown 草稿：
{state.get('draft_markdown')}

以下是可用的原始图片信息（路径或URL）：
{state.get('image_metadata')}

请在 Markdown 中插入合适的图片引用：
- 使用语法: ![说明](图片路径或URL)
- 图片路径必须来自 image_metadata 或网页原始URL
- 不要生成任何新图片，也不要虚构图片路径。
"""
    result = illustrator.invoke({"input": prompt})
    return {
        **state,
        "final_markdown": result["output"],
    }

def assembler_node_fn(state: ContentState) -> ContentState:
    prompt = f"""
这是最终 Markdown（包含图片引用）：
{state.get('final_markdown')}

文章标题：{state.get('title', '未命名文章')}
文章ID：{state.get('article_id')}

请调用 export_markdown 工具保存文件并返回下载链接信息。
"""
    result = assembler.invoke({"input": prompt})
    return {
        **state,
        "download_info": {"raw": result["output"]},
    }

def build_deep_content_graph():
    graph = StateGraph(ContentState)

    graph.add_node("planner", planner_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("writer", writer_node_fn)
    graph.add_node("illustrator", illustrator_node_fn)
    graph.add_node("assembler", assembler_node_fn)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "writer")
    graph.add_edge("writer", "illustrator")
    graph.add_edge("illustrator", "assembler")
    graph.add_edge("assembler", END)

    return graph.compile()

graph = build_deep_content_graph()
```

> 上面很多地方我放了 `"..."` 占位，你实际实现时可以让每个子 agent 输出结构化 JSON，然后用 `json.loads` 解析填到 `state`；LangGraph 文档和 community 示例里大量都是这种“LLM 产 JSON + 填 state”的模式[LangChain 文档+2DataCamp+2](https://docs.langchain.com/oss/python/langgraph/agentic-rag?utm_source=chatgpt.com)。

然后在 `langgraph.json` 里把 graph 指过去：

```
{
  "dependencies": ["."],
  "graphs": {
    "content-deep-agent": "content_agent.deep_agent_graph:graph"
  },
  "env": ".env",
  "python_version": "3.11"
}
```

后面的 `langgraph build` + `docker-compose` 方案可以直接复用我上一条给你的，只是 graph 名字换成 `content-deep-agent` 而已。