一、整体目标

- 抽出“LLM 图表规划组件”，统一 Excel / DB 的“列+样本数据+自然语言 → 多个 ChartSpec → ECharts option”的路径。

  ———

  二、任务清单（按执行顺序）

  1. 现状梳理
      - T1-1：整理 Excel 侧 LLM 使用点：_build_analysis_plan、build_chart_spec_from_analysis、_build_insight_text。
      - T1-2：整理 DB 侧 LLM 使用点：_build_db_analysis_plan、_build_db_chart_spec_from_result、_build_db_insight_text。
      - T1-3：总结两侧共性输入（columns/sample_rows/query）与输出（ChartSpec / 多图表）。
  2. 公共 LLM Runtime 抽象
      - T2-1：在 cv_agent/llm/runtime.py（或类似路径）新增模块：封装 get_settings → 构造 ChatOllama/ChatOpenAI。
      - T2-2：提供 invoke_llm_with_timeout(task_name, prompt, timeout_sec) -> str，统一 ThreadPool + FuturesTimeoutError 处理。
      - T2-3：Excel/DB 所有 _build_* 函数改用该 runtime，删掉重复初始化/超时代码。
  3. 通用 ChartSpec 规划模型与接口设计
      - T3-1：在公共位置定义 LLMTablePreview/LLMChartSpecPlan Pydantic 模型（或直接复用 ExcelChartSpec，外包一层 charts:
        List[ExcelChartSpec]）。
      - T3-2：设计统一的 Prompt 模板：输入 columns + sample_rows + query + source_kind(excel/db)，输出 {"charts":
        [{ChartSpec...}]}。
      - T3-3：在新模块中实现 plan_chart_specs_with_llm(preview, query, max_charts=3) -> List[ExcelChartSpec]。
  4. DB 侧接入通用 ChartSpec 规划器
      - T4-1：将 _build_db_chart_spec_from_result 迁移/重构为调用 plan_chart_specs_with_llm 的薄封装。
      - T4-2：让 DB 的 chart_spec_node 支持多图表（sql_results 与 charts 一一或多对一映射，先按“一次 SQL → 多图表”设计）。
      - T4-3：保持现有 DbAgentResponse 不变（以 charts 列表承载多个结果），更新日志字段（图表条数、字段映射）。
  5. Excel 侧渐进接入
      - T5-1：在 Excel Graph 中新增实验路径：可配置地绕过 ExcelAnalysisPlan + build_chart_spec_from_analysis，直接用
        plan_chart_specs_with_llm（例如加一个 flag）。
      - T5-2：对比两种路径输出：图表类型、x/y 轴选择、业务可读性，评估是否可以默认切到通用规划器。
      - T5-3：若效果满足预期，将 Excel 默认路径迁移到通用规划器，保留旧逻辑为后备策略（出错或 LLM 回答不规范时 fallback）。
  6. 测试与回归
      - T6-1：为新 runtime 和 plan_chart_specs_with_llm 写单元测试（mock LLM，验证 JSON 结构与异常路径）。
      - T6-2：更新/新增 DB Agent 测试用例，覆盖多图表场景和典型查询（按月金额+订单数等）。
      - T6-3：更新/新增 Excel Agent 测试用例，验证多图表规划、回退策略。
      - T6-4：在 Docker 环境下做端到端验证：
          - /v1/agent/db/chart 自然语言 → 多图表；
          - /v1/agent/excel/chart 自然语言 → 多图表。
  7. 文档与 memo
      - T7-1：更新 docs/design/db_agent_sql_agent.md，补充“LLM 图表规划组件”设计与时序图。
      - T7-2：在 docs/examples 增加统一规划器的调用示例（DB / Excel 各一）。
      - T7-3：按仓库规范在 docs/memo/当日日期.md 记录重构过程、关键决策与测试结论。
