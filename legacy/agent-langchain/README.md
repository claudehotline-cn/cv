# agent-langchain 项目（DB/Excel 图表 Agent for LangGraph）

该子项目用于在 `cv` 仓库中以 **LangGraph CLI + LangGraph Studio** 的方式单独调试与部署 DB/Excel 图表 Agent，
与原有 `agent/` 控制平面 Agent 解耦。对外 HTTP API 的暴露完全交给 `langgraph cli`，本项目自身不再维护手写的 FastAPI/LangServe 入口。

- 新增能力：
  - LangGraph CLI / Studio（基于 `agent-langchain/langgraph.json`）
  - 纯 Graph 形态的 DB/Excel Agent：`agent_langchain.db.graph:get_db_graph` / `agent_langchain.excel.graph:get_excel_graph`

> 注意：本项目不再直接暴露 ControlPlane 相关工具，也不再提供自定义 FastAPI 服务，仅聚焦 DB/Excel → ECharts 图表链路。

## 1. 依赖安装（本地开发）

在仓库根目录：

```bash
cd /home/chaisen/projects/cv
python -m venv .venv
source .venv/bin/activate
pip install -r agent-langchain/requirements.txt
```

## 2. 使用 LangGraph CLI / Studio

### 2.1 运行 Graph 一次性分析

在仓库根目录（确保当前 Python 环境可导入 `agent` 与 `agent-langchain`）：

```bash
cd /home/chaisen/projects/cv
langgraph run --config agent-langchain/langgraph.json db_chart \
  --input '{"query": "按月份统计订单金额和订单数，画一个双折线图", "session_id": "cli-test", "db_name": "cv_cp"}'
```

Excel 图表 Graph 用法类似：

```bash
langgraph run --config agent-langchain/langgraph.json excel_chart \
  --input '{"session_id": "excel-cli-test", "query": "根据表格数据画出销量趋势图"}'
```

### 2.2 启动 LangGraph Studio（同时暴露 API）

```bash
cd /home/chaisen/projects/cv
langgraph dev --config agent-langchain/langgraph.json --host 0.0.0.0 --port 8120
```

然后在浏览器访问 `http://localhost:8120`，即可通过 Studio 交互式调试：

- `db_chart` 图：数据库 → SQL Agent → 图表规划器 → ChartSpec → ECharts option
- `excel_chart` 图：Excel 表格 → 图表规划器 → ChartSpec → ECharts option

当你运行 `langgraph dev` 时，LangGraph 会自动起一个包含上述 Graph 的 HTTP 服务：

- `db_chart` / `excel_chart` 的 HTTP API 由 LangGraph CLI 暴露，你可以在 Studio 中查看其调用方式或导出 OpenAPI 说明；
- 本项目本身不再单独维护任何 FastAPI/LangServe 入口文件。
