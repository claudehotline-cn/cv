1. 定义请求/响应模型（API 协议）
  2. 对接 file 服务，验证 file_id -> Excel 文件 解析链路
  3. 实现 DataFrameStore 内存缓存（含简单 LRU/TTL）
  4. 实现 Excel 元信息读取（sheet 列表 + 预览统计）
  5. 实现 SelectSheetNode 的自动选 sheet 规则（先不用 LLM）
  6. 实现 loader.load_excel(file_id, sheet_name) 并接入缓存
  7. 选定 DataFrame 分析方案（pandas agent 或安全执行器），实现 analyze_df
  8. 为分析结果定义统一结构（analyzed_table：列名+数据+类型）
  9. 定义 ChartSpec / AgentChartResult 等 Pydantic 模型
  10. 设计 ChartSpec LLM Prompt + few-shot 示例
  11. 实现 build_chart_spec（含 JSON 解析+校验+重试）
  12. 实现 chart_spec_to_echarts_option（支持折线/柱状 + dataset.source）
  13. 设计 LangGraph state 结构并实现各节点（Input/SelectSheet/EnsureDF/Analyze/ChartSpec/BuildOption/Return）
  14. 注册 excel_chart_graph 到 agent 项目（能力入口或路由）
  15. 实现 POST /api/agent/excel/chart 接口并与 graph 打通
  16. 写单元测试：df_store/loader/echarts_builder
  17. 写集成测试：给定固定 Excel，验证能返回合理图表与 insight
  18. 用大 Excel 验证性能与超大表截断逻辑
  19. 补充日志埋点和基础指标
  20. 更新设计/接口文档，并在 docs/memo 记录本次任务