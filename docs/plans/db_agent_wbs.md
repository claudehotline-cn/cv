 一、WBS（按阶段拆解）

  1. 需求与架构对齐
     1.1 明确 DB Agent 目标（自然语言→SQL→表→ChartSpec→ECharts）
     1.2 评估现有 Excel Agent / DB Agent 复用点（ChartSpec/AnalyzedTable/Graph 结构）
     1.3 确认前端协议保持 /v1/agent/db/chart + DbAgentResponse 不变
  2. 基础设施与配置准备
     2.1 确认 agent/requirements.txt 已满足 SQLDatabase/SQL Agent 依赖
     2.2 补充/整理 DB 连接配置（db_host/db_port/db_user/db_password/db_default_name）
     2.3 设计多数据源/多数据库选择方案（db_name / datasource 映射）
  3. SQLDatabase 封装层
     3.1 新增 db/sql_agent.py 模块
     3.2 实现 get_sql_database(db_name)（基于 MySQL+pymysql DSN）
     3.3 封装 run_sql_query(db, sql, max_rows, timeout) 安全壳（只读 + 限流）
  4. SQL Agent 集成（核心）
     4.1 基于 SQLDatabase 试接 create_sql_query_chain（只生成 SQL）
     4.2 设计 + 实现 SQL 生成 Prompt（限制只用 SELECT，鼓励聚合+group by，避免全表扫）
     4.3 封装一个 plan_and_run_sql(request, db) 接口：返回 [{"sql","columns","rows"}]
     4.4 升级为 create_sql_agent（openai-tools/zero-shot-react-description），集成 schema introspection 与多表联查
     4.5 调整 Prompt 以适配 SQL Agent 工具调用模式（list_tables/get_table_info 等）
  5. LangGraph DB 流程改造
     5.1 在 db/graph.py 中新增 sql_agent_node
     5.2 load_schema 节点扩展：同时构造 SQLDatabase + 保留 DbSchemaPreview（供白名单/调试）
     5.3 用 sql_agent_node 替换现有 build_plan + DbAnalysisPlan + execute_chart_query 主路径
     5.4 调整 analyze_node：从 sql_results 构造 AnalyzedTable 列表（自动推断 group_by/metrics）
     5.5 复用 chart_spec_node / build_chart / insight_node，只做必要参数适配
     5.6 为旧的 DbAnalysisPlan/DbChartPlan/execute_chart_query 标记“废弃路径”，保留最小兼容或删除
  6. 安全 / 权限 / 性能策略落地
     6.1 在 run_sql_query 中实现 SQL 语句安全检查（仅 SELECT，黑名单/简单解析）
     6.2 基于 DbSchemaPreview 或 SQLDatabase 的表/列白名单校验（可选）
     6.3 在 Prompt 中明确数据量限制与时间范围约束（避免大表全扫）
     6.4 接入/透传 UserContext，为未来的表级权限控制预留入口
     6.5 为 SQL 执行增加行数上限、执行超时与异常日志字段
  7. HTTP 接口与前端契约确认
     7.1 确认 /v1/agent/db/chart 请求/响应模型无需变更，仅补文档
     7.2 在 server/api.py 中完善日志（记录 SQL Agent 相关关键信息，但不打印完整 SQL/数据）
     7.3 更新/新增 docs 示例（调用 /v1/agent/db/chart → 返回 ECharts option）
  8. 测试、观察与文档
     8.1 为 sql_agent.py 写单元测试（get_sql_database/run_sql_query 的正常与异常路径）
     8.2 为 db/graph.py 新增/调整节点级测试（mock LLM + mock SQLDatabase）
     8.3 增加 /v1/agent/db/chart 的集成测试脚本（含未配置 API Key、正常返回、异常兜底）
     8.4 检查 Prometheus 指标中增加/确认 db_chart 相关指标
     8.5 更新 docs/examples 与 docs/memo（记录设计与实现过程）
