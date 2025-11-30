## Agent 线程命名与审计一体化（TF1–TF3）

本文件对应 `openagent_integration_tasks.md` 中 Phase F-TF1/TF2/TF3 任务：规范 `thread_id` 命名策略，在 Agent/CP/前端之间对齐并补充审计字段，为后续线程级历史回放与统计打基础。

---

## 1. thread_id 命名策略（TF1）

统一约定：`thread_id` 使用 **前缀 + 业务键** 的形式，便于在日志和 UI 中按业务维度聚合。

- Pipeline 级：
  - `pipeline:{pipeline_name}`
  - 示例：`pipeline:cam_01`、`pipeline:demo_720p`
  - 使用场景：
    - Pipelines 详情页嵌入 Agent 面板（`Pipelines/Detail.vue`）；
    - 针对单个 pipeline 的排障、删除、drain、hotswap 等操作。
- 控制操作级：
  - `drain:{pipeline_name}`：以 drain 操作为主线的线程；
  - `delete:{pipeline_name}`：以删除操作为主线的线程；
  - `deploy:{pipeline_name}`：针对某个 pipeline 的部署/切换线程。
- 调试/临时会话：
  - `debug:{topic}`：针对某个问题主题的调试线程，如 `debug:va-latency`；
  - `manual-{timestamp}`：前端 Agent 控制台默认生成的手工线程 ID（`Agent.vue` 中保留现有行为）。

前端约定：

- `Agent.vue`：
  - 默认线程 ID 为 `manual-{timestamp}`，适合临时交互；
  - 提供“最近线程”列表，方便快速切换到指定 `thread_id`。
- `Pipelines/Detail.vue`：
  - 嵌入式 Agent 面板自动使用 `thread_id=pipeline:{name}`；
  - 便于后续在前端按 pipeline 汇总历史对话与控制记录。

---

## 2. Checkpoint 与线程级状态（TF2）

Agent 侧基于 LangGraph 的 checkpoint 能力按 `thread_id` 维度保存状态：

- 在 `agent/cv_agent/store/checkpoint.py` 中：
  - 默认使用 `MemorySaver`；
  - 可通过 `AGENT_CHECKPOINT_BACKEND=sqlite` 切换为 SQLite（`SqliteSaver.from_conn_string`），后续可扩展到 MySQL/Postgres。
- 在 `_invoke_agent_graph` / `_invoke_stategraph_agent` 中：
  - 将 `thread_id` 与 `user_id/role/tenant` 一起写入 `config["configurable"]`，LangGraph checkpoint 会据此将状态与线程绑定；
  - 对于无 thread_id 的一问一答调用，会为每次请求生成临时线程 ID（`invoke-{uuid}`），避免不同请求之间互相污染历史。

后续在扩展 TF2 时，可基于现有机制新增：

- 一个只读 API：按 `thread_id` 返回最近一次 checkpoint 的摘要：
  - 最近一条用户消息与 Agent 回复；
  - 最近一次控制操作摘要（可映射到 `AgentState.last_control_*` 字段）；
  - 最近一次 RAG 命中情况（例如 `cv_context.rag_applied` 标记）。
- 前端线程列表视图：消费上述 API，按 `pipeline/thread_id` 展示历史记录。

本次变更中，`AgentState` 已包含：

- `task`：当前路由意图（pipeline/debug/model），由 Router 节点维护；
- `last_control_op/last_control_mode/last_control_result`：为后续在 Graph 中落地“控制操作摘要持久化”预留字段；
- `cv_context.rag_applied`：RAG 决策节点命中后写入，用于标记本轮是否使用了文档检索。

---

## 3. CP 审计日志字段扩展（TF3）

在 cp-spring 中，通过 `AgentController` 代理 `/api/agent/threads/{thread_id}/invoke` 到 Agent 服务，并记录审计日志。

本次改动补充了以下字段：

- 请求侧（`agent.invoke.request`）：
  - `thread_id`：线程标识；
  - `agent_base`：转发的 Agent 基地址（`CP_AGENT_BASE_URL` 或默认 `http://agent:8000`）；
  - `op` / `mode` / `confirm`：如请求体中存在 `control` 字段，则解析并记录：
    - `op`：操作类型，例如 `pipeline.delete` / `pipeline.hotswap` / `pipeline.drain`；
    - `mode`：`plan` 或 `execute`；
    - `confirm`：执行阶段是否由前端显式确认。
- 响应侧（`agent.invoke.response`）：
  - `status`：HTTP 状态码；
  - `op` / `mode` / `success`：若响应体中存在 `control_result` 字段，则解析并记录：
    - `op`：回显的操作类型；
    - `mode`：回显的操作模式；
    - `success`：控制操作是否成功。
- 错误侧（`agent.invoke.error`）：
  - `status=502`；
  - `error`：转发失败时的异常信息。

结合 Agent 服务自身在 `_handle_control` 周边记录的日志（`user_id/role/tenant/thread_id/op/mode/success`），可以：

- 在后端日志中串联起：
  - 前端发起的高危操作请求；
  - CP 转发到 Agent 的 HTTP 调用；
  - Agent 内部执行控制工具的结果；
  - CP 返回前端的最终状态。
- 为后续在 Observability 中按 `thread_id/op/pipeline` 聚合 Agent 控制操作统计提供基础数据。

---

## 4. 后续工作提醒

- 线程列表视图（TE3/TF4）：
  - 需要在 Agent 侧补充按 `thread_id` 列出最近对话与控制摘要的 API；
  - 前端基于该 API 实现线程列表页面或侧边栏视图。
- 控制操作摘要持久化（TF2）：
  - 在 StateGraph 或 control 协议路径中落地 `AgentState.last_control_*` 的赋值；
  - 在 checkpoint 底层增加相应字段，便于快速查询“最后一次控制操作”的结果。

这些工作超出本轮变更的范围，可在后续 Phase F 迭代中继续推进。

