二、任务清单（按执行顺序，便于直接落地）

  1. 代码现状梳理
      - T1-1：阅读 agent/cv_agent/db/schema.py / loader.py / graph.py，整理现有 DB Agent 流程图
      - T1-2：对比 Excel Agent（excel/*）与 DB Agent，列出可复用的分析/ChartSpec 组件
  2. SQLDatabase 与配置接入
      - T2-1：在 agent/requirements.txt 确认/补充 langchain-community 中 SQLDatabase 相关依赖是否满足
      - T2-2：在 config.Settings 中补齐 db_default_name / 多数据源配置字段说明
      - T2-3：编写 db/sql_agent.py 骨架，定义 get_sql_database(db_name) 接口
  3. 安全执行壳 run_sql_query
      - T3-1：实现 run_sql_query(db, sql, max_rows)，内部使用 db.run(sql) 或底层连接执行
      - T3-2：在执行前增加简单 SQL 安全检查（只允许 SELECT，过滤危险关键字）
      - T3-3：增加日志（session_id/db_name/sql 摘要/rows count/duration）
  4. SQL 生成链（Query Chain → SQL Agent）
      - T4-1：基于 SQLDatabase + LLM，先实现 create_sql_query_chain 测试版，返回 SQL 字符串
      - T4-2：设计 SQL 生成 Prompt（包含：只读限制、聚合建议、时间范围建议、多表联查规则）
      - T4-3：封装 plan_and_run_sql(request, db)：内部调用 query chain + run_sql_query，返回 [{"sql","columns","rows"}]
      - T4-4：将 query chain 升级为 create_sql_agent，完成工具形式的 schema introspection 集成
  5. LangGraph DB 流程改造
      - T5-1：在 db/graph.py 中新增 sql_agent_node(state)，调用 plan_and_run_sql 写入 state["sql_results"]
      - T5-2：修改 load_schema_node，增加 SQLDatabase 创建并保存到 state（保留原 schema_preview）
      - T5-3：重写 analyze_node：从 sql_results 创建 DataFrame → AnalyzedTable 列表（自动推断 group_by/metrics）
      - T5-4：检查并最小调整 chart_spec_node / build_chart / insight_node 以适配新的 analyzed_list 来源
      - T5-5：将图结构从 load_schema → build_plan → analyze_db 改为 load_schema → sql_agent_node → analyze_db，旧节点保留/标记 deprecated
  6. 安全 / 权限 / 性能细化
      - T6-1：在 SQL Agent Prompt 中加入“只查白名单表/字段”的规则（先用描述性约束）
      - T6-2：对 sql_results 做行数限制与裁剪（最大 N 行），避免 ChartSpec 数据过大
      - T6-3：在 db_chart Handler 中透传 UserContext 至 Graph config，为后续权限控制预留信息
      - T6-4：增加针对 LLM 超时/SQL 超时的异常类型与用户错误信息（不要暴露内部堆栈）
  7. HTTP 接口与前端契约
      - T7-1：确认 /v1/agent/db/chart 的 Pydantic 模型无需变动，仅补充 docstring 说明“内部使用 SQL Agent”
      - T7-2：在 db_chart 的日志中增加 sql_agent_used=True/sql_count/rows_total 等字段（不打印敏感数据）
      - T7-3：在 docs/examples 新增一份调用示例（curl + 返回内容结构说明）
  8. 测试与观测
      - T8-1：为 db/sql_agent.py 写单元测试：
          - 正常 SQL 查询（mock SQLDatabase）
          - 非 SELECT SQL 被拒绝
      - T8-2：为 db/graph.py 新增 Graph 层单元测试：
          - mock SQL Agent 输出固定 sql_results，验证整个 graph 返回 DbAgentResponse
      - T8-3：扩展/新增集成测试脚本：调用 /v1/agent/db/chart，模拟问“按月份统计订单金额和订单数，画一个双折线图”
      - T8-4：检查 Prometheus 指标中 /v1/agent/db/chart 的请求数/延迟是否正常上报
  9. 文档与 docs/memo
      - T9-1：在设计文档中补充“DB→ECharts Agent（SQL Agent 版）”架构说明与时序图
      - T9-2：在 docs/memo/当日日期.md 记录每次实现/调整的任务完成情况与关键决策
      - T9-3：在 README 或专门文档中说明如何配置 DB、如何调试 SQL Agent 行为
