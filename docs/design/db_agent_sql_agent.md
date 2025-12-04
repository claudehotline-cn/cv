# DB→ECharts Agent（SQLDatabase + SQL Agent 版）设计说明

本文描述基于 LangChain SQLDatabase + SQL Query Chain/SQL Agent 的数据库分析 Agent 设计，串联“自然语言 → SQL → 表数据 → ChartSpec → ECharts option”的完整链路。

## 1. 目标与约束

- 目标：
  - 支持用户用自然语言对 MySQL 数据库发起分析请求；
  - 由 LLM 负责生成只读 SQL 并执行，得到聚合后的表数据；
  - 复用 Excel Agent 的图表流水线，自动选择维度/度量和图表类型，输出 ECharts option 与结论文本。
- 约束：
  - 只读：只允许 `SELECT` / `WITH` 查询，严禁任何写入或 DDL；
  - 限流：限制每次查询的最大行数（默认与 `excel_max_chart_rows` 一致）；
  - 可观测：关键路径必须打出 session_id/db_name/sql 摘要/行数/耗时等日志，并在 `/metrics` 中暴露 HTTP 指标。

## 2. 组件与数据流

### 2.1 关键组件

- `cv_agent.db.sql_agent`：
  - `get_sql_database(db_name)`：基于 `AGENT_DB_HOST/PORT/USER/PASSWORD` 构造 MySQL DSN，创建 `SQLDatabase`；
  - `_ensure_safe_select_sql(sql)`：校验 SQL 仅为只读查询并过滤高危关键字；
  - `run_sql_query(db, sql, max_rows, db_name)`：在 `SQLDatabase` 底层 engine 上执行只读查询，返回 `SqlQueryResult(columns, rows)`；
  - `plan_and_run_sql(request, db, db_name, max_rows)`：
    - 使用 `create_sql_query_chain(llm, db)`，在问题前追加约束性 prompt 生成 SQL；
    - 使用 `ThreadPoolExecutor` + `timeout_sec` 控制 LLM 超时；
    - 通过 `run_sql_query` 执行 SQL，返回 `List[SqlQueryResult]`。
- `cv_agent.db.graph`：
  - `load_schema_node`：加载 `DbSchemaPreview`（用于日志/白名单）并构造 `SQLDatabase`；
  - `sql_agent_node`：调用 `plan_and_run_sql` 获取 `sql_results`；
  - `analyze_db`：
    - 将 `SqlQueryResult` 转为 `DataFrame`；
    - 复用 Excel 侧 `_infer_column_types/_choose_group_by_column/_choose_metric_columns` 推断维度与度量；
    - 封装为 `AnalyzedTable` 列表；
  - `build_chart_spec`：使用 `_DbAsExcelRequest(query)` + `build_chart_spec_from_analysis` 生成 ChartSpec；
  - `build_chart`：调用 `build_chart_results_from_spec` 生成 `ExcelChartResult` 列表；
  - `build_insight`：通过 LLM 基于聚合结果生成整体结论。
- `cv_agent.server.api.db_chart`：HTTP Handler，负责：
  - 接收 `DbAnalysisRequest` 与 `UserContext`；
  - 通过 `invoke_db_chart_agent(request, user)` 调用 LangGraph；
  - 记录含 `sql_agent_used/sql_count/rows_total` 的日志，并上报 Prometheus HTTP 指标。

### 2.2 时序图

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant API as /v1/agent/db/chart
    participant Graph as DB StateGraph
    participant SQLA as sql_agent (SQLDatabase + LLM)
    participant DB as MySQL

    FE->>API: DbAnalysisRequest(session_id, db_name, query)
    API->>Graph: invoke_db_chart_agent(request, user)

    Graph->>Graph: load_schema_node\n- 解析 db_name\n- load_schema_preview\n- get_sql_database
    Graph->>SQLA: plan_and_run_sql(request, sql_db, db_name, max_rows)
    SQLA->>SQLA: create_sql_query_chain(llm, sql_db)\n+ 约束性 prompt 生成 SQL
    SQLA->>DB: run_sql_query(SELECT ...)
    DB-->>SQLA: columns + rows
    SQLA-->>Graph: [SqlQueryResult]

    Graph->>Graph: analyze_db\n- DataFrame\n- 推断 group_by/metrics\n- AnalyzedTable
    Graph->>Graph: build_chart_spec\n- ChartSpec
    Graph->>Graph: build_chart\n- ExcelChartResult 列表
    Graph->>Graph: build_insight\n- LLM 生成结论
    Graph-->>API: DbAgentResponse(used_db_name, charts, insight)
    API-->>FE: DbAgentResponse(JSON)
```

## 3. 配置说明

### 3.1 数据库相关（MySQL 与多数据源）

由 `cv_agent.config.Settings` 管理，环境变量前缀为 `AGENT_DB_*`：

- `AGENT_DB_HOST` (`db_host`，默认 `mysql`)：MySQL 主机名或地址；
- `AGENT_DB_PORT` (`db_port`，默认 `3306`)：MySQL 端口；
- `AGENT_DB_USER` (`db_user`，默认 `root`)：只读分析账号；
- `AGENT_DB_PASSWORD` (`db_password`，默认 `123456`)：账号密码（内部通过 `quote_plus` 做最小转义）；
- `AGENT_DB_DEFAULT_NAME` (`db_default_name`，默认 `cv_cp`)：默认数据库名，当请求未显式指定 `db_name` 时使用。
- `AGENT_DB_EXTRA_DATABASES` (`db_extra_databases`，默认 `{}`)：额外数据源别名到数据库名的映射，例如 `{"reporting": "cv_reporting"}`。当 `DbAnalysisRequest.db_name` 与某个别名匹配时，内部会自动映射为对应的实际数据库名。

SQLDatabase 连接串示例（单数据源）：

```text
mysql+pymysql://user:password@host:port/db_name
```

多数据源使用示例：

- `.env` 中配置：

  ```env
  AGENT_DB_DEFAULT_NAME=cv_cp
  AGENT_DB_EXTRA_DATABASES={"reporting": "cv_reporting", "orders": "cv_orders"}
  ```

- 调用 `/v1/agent/db/chart` 时：

  ```json
  { "session_id": "s-db-01", "db_name": "reporting", "query": "按月份统计报表金额..." }
  ```

  内部会将 `db_name="reporting"` 映射为实际数据库名 `cv_reporting`。

### 3.2 LLM 与超时

由通用 LLM 配置控制：

- `AGENT_LLM_PROVIDER` (`llm_provider`，`openai`/`ollama`)；
- `OPENAI_API_KEY`：OpenAI 兼容模型的 API Key（provider=openai 时必需）；
- `AGENT_OPENAI_MODEL` (`llm_model`)：模型名称，例如 `gpt-4o-mini`；
- `AGENT_OLLAMA_BASE_URL`：Ollama 服务地址。

超时相关：

- `AGENT_REQUEST_TIMEOUT` (`request_timeout_sec`，默认 30s)：
  - 用于 LLM 调用超时控制（`plan_and_run_sql` 使用 `ThreadPoolExecutor` 包装）；
  - 超时会抛出 `TimeoutError`，在 `db_chart` 中以 HTTP 504 形式返回。

### 3.3 行数与性能

- `AGENT_EXCEL_MAX_CHART_ROWS` (`excel_max_chart_rows`，默认 500)：
  - 控制单个图表的最大数据行数；
  - SQL Agent 在生成 SQL 后，执行时会限制从数据库读取的最大行数；
  - 分析节点在构造 `DataFrame` 时也会再次按该上限截断。

## 4. 安全与权限

### 4.1 SQL 安全壳

- 所有由 LLM 生成的 SQL 均通过 `_ensure_safe_select_sql` 校验：
  - 只允许以 `SELECT` 或 `WITH` 开头；
  - 禁止出现 `INSERT/UPDATE/DELETE/DROP/TRUNCATE/ALTER/CREATE/MERGE/GRANT/REVOKE` 等关键字；
  - 校验失败抛出 `ValueError`，由上层捕获并转换为用户可理解的错误。

### 4.2 用户上下文透传

- `db_chart` Handler 通过 `UserContext` 读取 `X-User-Id/X-User-Role/X-Tenant` 头；
- 在调用 `invoke_db_chart_agent` 时，将用户信息写入 LangGraph config：
  - `config["configurable"] = {"user_id", "role", "tenant"}`；
- 当前 Graph 内部尚未使用这些字段做表级权限控制，但为后续基于租户或角色的白名单策略预留了接口。

## 5. 调试与观测

### 5.1 日志字段

- `db.sql.*` 日志：
  - `db.sql.get_sql_database`: DSN（脱敏后）；
  - `db.sql.plan_and_run_sql.start/done`: `db_name/session_id/rows/columns`；
  - `db.sql.run_sql_query`: `db_name/sql 摘要/rows/columns`。
- `db.graph.*` 日志：
  - `load_schema`: `session_id/db_name/tables`；
  - `sql_agent_node`: `db_name/max_rows/results`；
  - `analyze_db`: `db_name/sql_results/charts`；
  - `build_chart_spec/build_chart/build_insight`: 图表 ID/series 数/rows 等。
- HTTP 层 `db_chart`：
  - `start/done/failed/timeout` 日志附带：`session_id/db_name/used_db_name/user_id/role/tenant/sql_agent_used/sql_count/rows_total/duration_ms`。

### 5.2 Prometheus 指标

在启用 `prometheus_client` 的情况下：

- `_record_http_metrics("/v1/agent/db/chart", "POST", duration_ms)`：
  - `cv_agent_http_requests_total{path="/v1/agent/db/chart", method="POST"}`；
  - `cv_agent_http_request_duration_seconds{path="/v1/agent/db/chart", method="POST"}`。

可通过 `/metrics` 端点抓取，用于监控 DB Agent 的调用频次与延迟分布。

## 6. 使用与扩展建议

- 若需支持多数据源/多数据库，可在配置中引入 `datasource`→DSN 的映射，并在 `DbAnalysisRequest` 中增加 `datasource` 字段，以选择不同的 `SQLDatabase`；
- 如需完整的 `create_sql_agent` 工具链（带多轮工具调用与解释能力），可以在 `sql_agent.py` 中新增一个基于 SQL Agent 的 LLM 节点，用于：
  - 先通过工具理解 schema/关系；
  - 再生成多条 SQL 或更复杂的联查方案；
  - 当前版本已通过 `create_sql_query_chain` 实现了“自动写 SQL + 我方执行”的主路径，后续升级可以在不改变 HTTP 协议的前提下进行。  
