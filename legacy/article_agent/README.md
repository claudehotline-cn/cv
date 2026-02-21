# article_agent 项目（内容整理 Deep Agent for LangGraph）

本子项目用于实现一个基于 **LangGraph Deep Agent** 的内容整理 Agent，支持：

- 从超链接与上传文件中获取内容；
- 对多来源内容进行规划、研究、写作与插图策展；
- 生成图文并茂的 Markdown 文档，并落盘为 `.md` 文件；
- 返回文章与图片资源的下载链接，供前端 Agent Chat UI 使用。

本项目仅通过 **LangGraph CLI / Studio** 对外暴露 HTTP API，自身不再维护 FastAPI/LangServe 等自定义服务。

## 1. 安装依赖（本地开发）

在仓库根目录：

```bash
cd /home/chaisen/projects/cv
python -m venv .venv
source .venv/bin/activate
pip install -r article_agent/requirements.txt
```

## 2. 使用 LangGraph CLI / Studio

### 2.1 命令行一次性生成文章

```bash
cd /home/chaisen/projects/cv
langgraph run --config article_agent/langgraph.json content-deep-agent \
  --input '{
    "instruction": "为技术博客读者整理一篇介绍 LangGraph Deep Agent 的文章，语气专业但亲切。",
    "urls": ["https://example.com/langgraph-deep-agent"],
    "file_paths": [],
    "article_id": "demo-article-001",
    "title": "LangGraph Deep Agent 实战：内容整理工作流"
  }'
```

> `instruction` / `urls` / `file_paths` 等字段对应 ContentState 中的输入字段，详情见 `article_agent/content_state.py`。

### 2.2 启动 LangGraph Studio（同时暴露 HTTP API）

```bash
cd /home/chaisen/projects/cv
langgraph dev --config article_agent/langgraph.json --host 0.0.0.0 --port 8130
```

浏览器访问 `http://localhost:8130` 可在 Studio 中调试：

- `content-deep-agent` / `content-chat-agent` Graph：均指向同一个基于 DeepAgents 的内容整理 Deep Agent；
- 可以在 Studio 中查看 Deep Agent 的 messages 状态与工具调用轨迹。

LangGraph 会自动暴露 HTTP 接口：

- 命令行 / Studio 示例可以继续使用 Graph ID `content-deep-agent`；
- 前端 Agent Chat UI 推荐使用 Graph ID `content-chat-agent`。
