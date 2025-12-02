# Agent 前端集成与数据契约

本文档描述 Python `cv_agent` 服务与前端控制台的主要交互方式，约定 `/v1/agent/*` 系列接口的请求/响应结构，尤其是 `agent_data` 时间线结构与线程摘要、统计信息，便于前端统一展示 Agent 的思考过程与控制操作结果。

## 1. 核心 HTTP 接口

### 1.1 一问一答：`POST /v1/agent/invoke`

- **请求体**
  - `messages: Message[]`
    - `role: "user" | "assistant" | "system" | "tool"`
    - `content: string`
  - `control?: ControlRequest`
    - `op: "pipeline.delete" | "pipeline.hotswap" | "pipeline.drain"`
    - `mode: "plan" | "execute"`
    - `params: { pipeline_name?, node?, model_uri?, timeout_sec? }`
    - `confirm: boolean`（仅在 `mode=execute` 且高危操作时需要 `true`）

- **响应体 `AgentInvokeResponse`**
  - `message: { role, content }`：Agent 最终回复（用于对话气泡）
  - `raw_state?: object`：完整 LangGraph 状态（仅部分接口返回，前端一般不直接使用）
  - `control_result?: ControlResult`
    - `op, mode, success`
    - `plan?: object`：plan_* 工具的原始规划结果
    - `result?: object`：执行阶段的原始结果（例如 CP HTTP 返回 payload）
    - `plan_steps?: object[]`：抽象后的计划步骤列表（前端推荐展示字段，可直接渲染为步骤卡片）
    - `execute_result?: object`：执行阶段聚合结果（包含状态/错误信息等）
    - `error?: string`：失败时的错误信息
  - `agent_data?: AgentData`

### 1.2 线程对话：`POST /v1/agent/threads/{thread_id}/invoke`

- 语义与 `/v1/agent/invoke` 基本一致，增加：
  - `thread_id`：路径参数，标识一个持久线程
  - Agent 会基于 LangGraph checkpoint 以 `thread_id` 为 key 拼接历史消息并持续更新摘要

### 1.3 StateGraph 显式入口：`POST /v1/agent/stategraph/threads/{thread_id}/invoke`

- 与 `threads/{thread_id}/invoke` 一致，但显式走 StateGraph 实现路径（用于灰度/调试），前端仅在需要对比行为时使用。

## 2. `agent_data` 时间线结构

`agent_data` 字段用于前端还原一次调用内部的“思考-工具-响应”步骤，以近似 openagent 的时间线视图。

### 2.1 顶层结构

```jsonc
{
  "status": "done",
  "steps": [
    {
      "id": 0,
      "type": "user",
      "content": "列出当前所有 pipeline。"
    },
    {
      "id": 1,
      "type": "thinking",
      "content": "正在根据当前 pipelines 规划下一步操作……"
    },
    {
      "id": 2,
      "type": "tool",
      "tool_name": "list_pipelines",
      "tool_call_id": "call-xxx",
      "content": "准备调用工具 list_pipelines",
      "status": "pending"
    },
    {
      "id": 3,
      "type": "tool",
      "tool_call_id": "call-xxx",
      "content": "{ \"pipelines\": [ ... ] }",
      "status": "success"
    },
    {
      "id": 4,
      "type": "response",
      "content": "当前存在 N 个 pipeline：...",
      "status": "ok"
    }
  ]
}
```

- `status: "done"`：当前仅返回终态；未来可扩展为加载中/部分完成等状态。
- `steps: Step[]`：按照模型与工具消息顺序展开的步骤列表。

### 2.2 Step 字段约定

- 通用字段
  - `id: number`：自增序号，便于前端稳定渲染。
  - `type: "user" | "thinking" | "tool" | "response"`
  - `content: string`：该步骤的主要文本内容。

- 工具相关字段（仅当 `type="tool"` 时出现）
  - `tool_name?: string`：当步骤表示“准备调用某工具”时，记录工具名称。
  - `tool_call_id?: string`：与 LangChain/StateGraph 中的 tool_call_id 对齐，用于将“调用”和“结果”关联。
  - `status?: "pending" | "success" | "error" | "ok"`：
    - `pending`：工具调用计划阶段；
    - `success`：对应 ToolMessage 成功返回；
    - `error`：预留给未来显式错误场景；
    - `ok`：一般响应步骤的成功状态。

前端可以基于 `type + status` 决定图标和颜色，例如：

- `user`：用户气泡；
- `thinking`：带“思考中”提示的系统气泡；
- `tool` + `pending`：工具调用计划；
- `tool` + `success`：工具返回结果；
- `response`：模型最终回答。

## 3. 线程摘要与统计接口

### 3.1 线程列表：`GET /v1/agent/threads`

- 返回值：`ThreadSummary[]`，按 `updated_at` 倒序。
- 字段（与 `cv_agent.store.thread_summary.ThreadSummary` 一致）：
  - `thread_id: string`
  - `user_id?: string`
  - `role?: string`
  - `tenant?: string`
  - `last_user_message?: string`
  - `last_assistant_message?: string`
  - `last_control_op?: string`
  - `last_control_mode?: string`
  - `last_control_success?: bool`
  - `last_error?: string`：若最近一次控制操作失败，则记录 `ControlResult.error`；否则保持上一次的错误或为空。
  - `updated_at: string`（ISO-8601，UTC）

前端常见用法：

- 作为“线程列表”视图的数据源；
- 展示最近一条用户/Agent 摘要；
- 标记最近一次控制操作是否成功（例如以状态徽标显示）。

### 3.2 线程摘要：`GET /v1/agent/threads/{thread_id}/summary`

- 若存在摘要，直接返回与 `ThreadSummary` 同构的对象；
- 若不存在，则返回所有字段为 `null` 的占位结构，方便前端统一处理：
  - `thread_id`
  - `last_user_message`
  - `last_assistant_message`
  - `last_control_op`
  - `last_control_mode`
  - `last_control_success`
  - `last_error`
  - `updated_at`

### 3.3 控制统计：`GET /v1/agent/stats`

- 聚合维度：`(op, mode)`；来源于 `_AGENT_STATS`：
  - `op: string`：控制操作类型，例如 `"pipeline.delete"`。
  - `mode: "plan" | "execute"`。
  - `success_count: int`。
  - `failure_count: int`。

前端可以据此构建：

- 控制操作看板（删除/hotswap/drain 的成功率和调用次数）；
- 按操作类型/模式的分布图表。

## 4. 权限与多租户约定

### 4.1 用户上下文（请求头）

所有 `/v1/agent/*` 接口都可以通过 HTTP 头部携带用户上下文：

- `X-User-Id` → `user_id`
- `X-User-Role` → `role`，示例：`admin` / `operator` / `viewer`
- `X-Tenant` → `tenant`，用于多租户隔离

后端会在：

- StateGraph 配置中透传 `user_id/role/tenant/thread_id`；
- 控制协议 `_handle_control()` 中做最小权限校验：
  - 任意角色均可 `mode=plan`；
  - 仅 `admin/administrator/operator` 允许对 `pipeline.delete/hotswap/drain` 执行 `mode=execute`；
  - 同时需要 `confirm=true` 才会真正调用高危工具。

### 4.2 多租户透传

在控制协议和部分工具调用中，Agent 会将 `UserContext.tenant` 通过 `X-Tenant` 头部透传到 ControlPlane HTTP 接口（如 `/api/pipelines`、`/api/control/*`）。

ControlPlane 负责最终的跨租户校验，例如：

- 若请求访问不属于当前 tenant 的 pipeline，返回明确的权限/租户错误；
- Agent 将错误包装到 `ControlResult.error` 中，并写入线程摘要的 `last_error` 字段。

## 5. 前端集成建议

1. 在对话视图中：
   - 使用 `message` 渲染主对话；
   - 使用 `agent_data.steps` 在侧边栏或展开面板中展示“思考与工具调用时间线”。
2. 在线程列表页：
   - 使用 `/v1/agent/threads` 作为数据源，显示 `last_user_message`、`last_assistant_message` 与最近一次控制操作状态。
3. 在线程详情页：
   - 使用 `/v1/agent/threads/{id}/summary` 补充最近一次错误信息与控制操作元数据。
4. 在监控/运维视图：
   - 使用 `/v1/agent/stats` 构建控制操作成功率/失败率看板，与日志系统、Prometheus 指标结合。
