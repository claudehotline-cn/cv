# CONTEXT（2025-12-02，Agent 控制台与工具链集成现状）

本文件汇总当前关于 **控制平面 Agent（Python cv_agent + cp-spring 代理）与前端 Agent 控制台** 的关键讨论与实现状态，侧重系统提示词迁移、工具调用链路、前端集成与通过 Chrome DevTools MCP 的验证结果，用于指导后续优化与排障。

---

## 一、整体架构与运行环境

- 组件拓扑：
  - **cp-spring**：Spring Boot 控制平面，实现 `/api/*` 与 `/metrics` 等 HTTP/SSE 接口，并通过 gRPC 调用 `video-analyzer`（VA）和 `video-source-manager`（VSM）。
  - **cv_agent（Python）**：基于 LangGraph 的控制平面 Agent 服务，提供 `/v1/agent/*` API，内部维护 ReAct Agent 与 StateGraph Agent 两套实现，当前对外主要使用 StateGraph Agent。
  - **web-frontend**：前端工程，`/agent` 页面提供 Agent 控制台 UI，通过 `/api/agent/threads/{threadId}/invoke` 与 cp-spring 交互。
  - **C++ controlplane（cp）**：仍存在但不再对 web / agent 暴露端口，仅作为参考实现与回退选项。
- 部署与测试环境：
  - 所有服务以 Docker 方式部署，cp-spring 暴露 `18080`，web 暴露 `8080`。
  - 测试时在 WSL 内使用 headless Chrome，通过 DevTools MCP 访问 `http://192.168.50.78:8080/#/agent`，后端 API 统一指向 `http://127.0.0.1:18080`。
  - DevTools MCP 仅抓取关键网络请求（`/api/agent/*`、`/api/va/runtime`、`/api/_metrics/summary`）和少量控制台错误，避免大体量快照。

---

## 二、系统提示词的归属与行为

- C++ CP 侧：
  - 在 `controlplane/src/server/main.cpp` 中定义 `kAgentSystemPrompt`，描述控制平面 Agent 的职责、能力与高危操作流程（先 plan 再执行、禁止臆造 pipeline/接口等）。
  - C++ CP 在处理 `/api/agent/threads/{id}/invoke` 时，会解析请求体并在 `messages[0]` 位置插入一条 `role=system` 的系统提示消息，然后再转发到 Agent。
- cp-spring 侧：
  - 本次对话中，`controlplane-spring/src/main/java/com/cv/cp/controller/AgentController.java` 增强了 `/api/agent/threads/{threadId}/invoke`：
    - 新增 `AGENT_SYSTEM_PROMPT` 常量，内容与 C++ `kAgentSystemPrompt` 保持一致。
    - 在代理请求到 Agent 前，若 body 中存在 `messages` 数组，会在首位插入 system 消息，保证所有从 cp-spring 出口的 Agent 调用都有统一的系统提示。
    - 继续保留审计日志（请求的 `op/mode/confirm` 与响应的 `control_result` 要点）。
- Python Agent 侧：
  - 原先在 `agent/cv_agent/graph/control_plane.py` 的 `_agent_step` 中，若消息中缺少 `SystemMessage` 会自动插入一段简化版系统提示。
  - 为避免重复注入并统一提示来源，本次对话中已移除该自动注入逻辑，Agent 现在只使用上游（cp-spring 或 C++ CP）插入的 system 消息。

结论：系统提示词的“权威版本”已经前移到控制平面层（C++ CP 与 cp-spring），Python Agent 只负责消费，不再自行添加。

---

## 三、Agent 工具调用链路与当前行为

- 工具定义与注册：
  - `agent/cv_agent/tools/pipelines.py` 定义了与管线管理相关的异步工具：
    - 列表与状态：`list_pipelines_tool`、`get_pipeline_status_tool`。
    - 规划工具：`plan_update_pipeline_config_tool`、`plan_delete_pipeline_tool`、`plan_hotswap_model_tool`、`plan_drain_pipeline_tool`。
    - 执行工具：`delete_pipeline_tool`、`hotswap_model_tool`、`drain_pipeline_tool`。
  - 工具通过 `cv_agent/tools/__init__.py` 注册到全局 `TOOL_REGISTRY`，并在构建 StateGraph 时整体注入。
- StateGraph 与工具执行：
  - `AgentState` 中维护 `messages`、`task`、`plan`、`pending_tools` 等字段，Router 节点根据最近一条用户消息将 `task` 粗分为 `pipeline` / `debug` / `model`。
  - 各 Agent 节点调用 LLM 生成回复与 `tool_calls`，ToolExecutor 节点读取最后一条 AI 消息中的 `tool_calls` 并顺序执行工具，将结果以 `ToolMessage` 形式追加到消息流中。
  - 本次对话中，ToolExecutor 从同步 `invoke` 调用改为优先异步 `ainvoke`：
    - 若工具对象存在 `ainvoke`，则使用 `await tool_impl.ainvoke(args)`；
    - 否则回退到 `tool_impl.invoke(args)`。
    - 该改动修复了之前在 `list_pipelines` 工具上出现的 `StructuredTool does not support sync invocation` 运行时错误。
- agent_data 构建：
  - `agent/cv_agent/server/api.py` 中 `_build_agent_data_from_state` 会遍历 `state["messages"]`，将其归类为：
    - `type=user`：用户输入；
    - `type=thinking` + `type=tool`：带 `tool_calls` 的 AI 消息及其计划调用；
    - `type=tool`：实际的 ToolMessage 输出；
    - `type=response`：纯文本 AI 回复。
  - 前端 `web-front/src/views/Agent.vue` 使用 `resp.agent_data.steps` 在右侧“Agent 思考流程”面板渲染时间线。
- 当前观察到的行为：
  - 早期请求中，`agent_data.steps` 中出现过 `type=tool` 步骤，并在 `raw_state.messages` 中看到 ToolMessage，内容类似：
    - “Tool list_pipelines execution error: StructuredTool does not support sync invocation.”
  - 在 ToolExecutor 异步化并重新部署 agent 容器后：
    - 新请求中不再出现上述同步调用错误；
    - 但 LLM 在多轮失败上下文下不再产生新的 `tool_calls`，`agent_data.steps` 仅包含 `user/response`，回复集中在“无法获取 pipelines 列表，请先排查控制平面/权限/网络”等说明。
  - 当同一线程内积累多轮复杂指令时，StateGraph 会触发递归深度限制，追加一条 AI 消息：
    - “Agent 在当前问题上的思考与工具调用步数超过上限，请缩小问题范围或分步提问后重试。”

结论：底层工具执行器的同步调用问题已解决，但在当前提示词和历史对话共同作用下，大模型对“列出 pipelines”类请求更多选择给出解释与排障建议，而不是再次尝试调用控制平面工具。

---

## 四、前端 Agent 控制台与 DevTools MCP 验证

- Agent 页面结构与交互：
  - `/agent` 页面采用接近 openAgent Chat 的布局：
    - 顶部：标题、线程 ID 输入框（可修改）、 Agent 启用状态标签、历史线程入口。
    - 主区域：左侧为对话气泡区，右侧为侧栏卡片：
      - “Agent 思考流程”：使用 `agent_data.steps` 渲染纵向时间线，区分 user/thinking/tool/response。
      - “最近控制结果”：展示结构化控制协议结果（op/mode/success 等）。
      - （可选）工具步骤视图：突出工具相关步骤，便于排障。
    - 输入区域支持多行文本与快捷发送（Ctrl+Enter），发送按钮会在 Agent 禁用或输入为空时置灰。
- DevTools MCP 测试方式：
  - 在 WSL 内使用 headless Chrome，通过 DevTools MCP：
    - 导航到 `http://192.168.50.78:8080/#/agent`；
    - 通过 `runtime_evaluate` 自动填充指令并触发“发送”按钮；
    - 通过 `network_list_requests` 与 `network_get_request` 查看最近一个 `/api/agent/threads/{threadId}/invoke` 请求与响应。
  - 关键观察点：
    - `/api/va/runtime` 与 `/api/_metrics/summary` 在 cp-spring 增强后均返回 200，解决了早期前端偶发的 404/ERR_FAILED。
    - 使用固定线程 ID（如 `test-openagent-tools`）多轮对话时，后期会出现递归上限提示；即便更换为新线程 ID，LLM 仍可能延续“解释与排障”为主的策略。
    - 在最近几次请求中，响应的 `raw_state.messages` 最后一条 AI 消息均未包含 `tool_calls`，`agent_data.steps` 中没有新的 `type=tool` 步骤。

---

## 五、当前主要问题与改进方向（摘要）

- 工具调用缺乏可靠触发：
  - 在异常恢复后，Agent 对“查询 pipelines 状态”的问题仍倾向用自然语言说明，而非再尝试工具调用，导致前端“思考流程”中无法直观看到工具使用轨迹。
  - 需要结合系统提示词与 few-shot 示例，强化“涉及实时状态查询时优先实际调用控制平面工具”的约束。
- 可观测性不足：
  - 当前缺乏针对 Agent 工具调用的细粒度指标（如 per-tool 调用次数、成功率、错误类型分布），排障主要依赖日志与 DevTools MCP 手工检查。
  - 建议在 Agent 内部增加轻量级统计，并通过 `/v1/agent/stats` 或新的观测端点向 cp-spring 暴露。
- 前端反馈不够透明：
  - 当回复未使用工具时，前端用户很难判断答案是基于实时数据还是仅基于文档与推理。
  - 后续可以在 UI 上增加简单标记（如“本次回答未访问后端状态”），并在必要时提供“强制刷新状态”的入口。

本 CONTEXT 将作为后续 ROADMAP 的基础，指导对 Agent 工具链、提示词策略、观测与前端交互的迭代规划。

