P0（必须尽快完成，保障可用性）

1. 补齐并统一 cv_agent.tools 工具层

 新建包 cv_agent/tools/，整理文件结构：

 cv_agent/tools/__init__.py：实现 get_all_tools(settings)，集中返回所有 Tool。

 cv_agent/tools/pipelines.py：封装所有 CP 管理相关工具：

 _fetch_pipelines / _fetch_pipeline_status

 _call_delete_pipeline

 _call_hotswap_model

 _call_drain_pipeline

 为上述操作封装 LangChain Tool（带 pydantic 输入/输出模型）。

 cv_agent/tools/rag.py：

 实现 SearchCvDocsInput（pydantic 模型）。

 实现 search_cv_docs_tool（LangChain Tool，内部调 PG 向量检索）。

 确认 cv_agent/graph/control_plane.py 和 cv_agent/server/api.py 的 import 正常工作。

2. 让 StateGraph 成为主 Agent 路径

 在 cv_agent/graph/control_plane.py 里梳理：

 _build_stategraph_agent()：确认 Router → RAG 节点 → Agent 节点 → Tools 节点 的 DAG 没有死循环。

 _build_agent()（基于 create_react_agent）标注为“兼容模式”。

 在 cv_agent/server/api.py 中调整：

 invoke_agent() / invoke_agent_thread() 主路径统一走_invoke_stategraph_agent()。

 _invoke_agent_graph() 仅在 llm_provider=openai 且缺少 api_key 时作为 fallback 使用。

3. 完善 checkpoint，至少从内存升级到 sqlite

 在 cv_agent/store/checkpoint.py 中：

 真正接入 SqliteSaver（目前只判断 env，但没完整配置）。

 支持通过环境变量指定 sqlite 文件路径（挂 volume，避免容器重启丢数据）。

 部署层：

 docker-compose / k8s 部署里为 Agent 挂载一个持久化卷给 sqlite。

 确认以下场景可用：

 线程对话在容器重启后仍能恢复。

 多并发 thread 下的状态切换正常。

P1（重要优化，提升工程完整度）
4. 权限控制：基于 UserContext 做最小控制

 在 cv_agent/server/api.py 中增加权限检查函数：

def _check_permission(user: UserContext, op: str) -> None:
    ...

 为不同 role 定义最小权限（先写死也行）：

 普通用户：禁止 pipeline.delete / pipeline.hotswap / pipeline.drain 的 execute。

 管理员：允许高危操作，但仍需 mode=plan + confirm=true。

 多租户约束：

 在发 CP 请求时透传 tenant。

 检查 pipeline 是否属于该 tenant（先在 CP 侧做简单校验）。

5. 统一 control 调用路径和 Tool 抽象

 重构 _handle_control()：

 内部不直接调用 _call_*，而是复用 cv_agent.tools.pipelines 中的 Tool 实现（可以在 Tool 内再调用 _call_*）。

 确保“结构化 ControlRequest”和“自然语言触发工具”走的是同一套工具实现。

 为 plan/execute/confirm 设计统一结构：

 ControlResult 中清晰区分：

 plan_steps: 计划步骤列表。

 execute_result: 实际执行结果（成功/失败/错误信息）。

6. 定义前端展示用的 agent_data / 线程摘要 schema

 在 AgentInvokeResponse 的 agent_data 中固定 JSON 结构，例如：

{
  "steps": [
    { "type": "thought", "content": "...", "time": "..." },
    { "type": "tool_call", "tool": "pipeline.hotswap", "input": {...}, "output": {...} },
    ...
  ]
}

 在 cv_agent/store/thread_summary.py 中：

 保证 summary 里至少包含：

 最后一次 user/assistant 摘要。

 最后一次 control 操作及状态。

 最近一次错误（如果有）。

 为 /v1/agent/threads、/summary、/stats 写一份简单的前端消费文档（可以放到 docs/design/agent-ui.md）。

7. 完善 RAG 的接入流程

 rag/pg_store.py：

 确认连接 Postgres 的 DSN 通过 Settings 统一配置。

 抽象出基础查询接口（按文档类型/模块过滤）。

 rag/ingest_docs.py：

 增加 CLI 参数：指定 docs 根目录 / 文档类型。

 加上简单的去重逻辑（避免多次 ingest 重复写入）。

 cv_agent/tools/rag.py：

 将 PG 查询封装为 LangChain Tool（search_cv_docs_tool），可按模块/关键字检索项目文档。

P2（增强可维护性与可观测性）
8. 增加关键路径测试（pytest）

 新建 agent/tests/ 目录，引入 pytest。

 编写核心测试用例：

 Router：给定不同 user 输入，断言 AgentState.task 正确（pipeline/debug/model）。

 Control plan/execute：

 pipeline.delete 的 plan 返回正确步骤。

 execute 无 confirm=true 时拒绝。

 LangGraph 异常场景：

 GraphRecursionError 返回自定义错误提示。

 INVALID_CHAT_HISTORY 时自动创建新 thread_id 并成功执行。

 RAG 工具：给定特定文档和 query，断言返回的 snippet 包含预期关键字。

9. 日志 & 指标

 HTTP 层：

 记录每次请求的 thread_id、user_id、op、mode、耗时、状态码。

 Agent 层：

 对每次 Tool 调用记录：tool 名称、耗时、是否成功。

 将 _AGENT_STATS 后面改成可选的 Prometheus 指标。

P3（中长期演进方向）
10. 多 Agent 拆分与更细粒度任务路由

 在 StateGraph 里抽象出多个“子 Agent”：

 Pipeline 管理 Agent

 调试/日志 Agent

 模型与训练 Agent（预留）

 Router 节点根据意图把请求派发到不同子 Agent，简化每个 Agent 的职责。

11. 更强的 checkpoint 后端（可考虑 MySQL）

 设计一张 agent_checkpoints 表（thread_id + checkpoint JSON）。

 实现基于 MySQL 的简单 checkpoint 接口，替换或补充 sqlite。

 配合生产多实例部署，实现“不同 Agent 副本共享线程状态”。
