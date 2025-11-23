## Agent 前端交互协议（高危控制操作）

本协议用于约定 **Web 前端** 与 **Agent 服务** 在高危控制操作（delete/hotswap/drain）上的交互方式，目标：

- 所有危险操作必须先 **plan** 再 **execute**；
- plan 阶段只读，展示 diff 与计划；
- execute 阶段必须显式 `confirm=true` 才允许真正修改系统。

---

## 1. 请求结构（带 control 字段）

接口统一使用：

- `POST /v1/agent/invoke`
- `POST /v1/agent/threads/{thread_id}/invoke`

请求体在原有 `messages` 基础上新增可选 `control` 字段：

```json
{
  "messages": [
    { "role": "user", "content": "请删除 pipeline cam_01。" }
  ],
  "control": {
    "op": "pipeline.delete",
    "mode": "plan",
    "params": {
      "pipeline_name": "cam_01",
      "node": null,
      "model_uri": null,
      "timeout_sec": null
    },
    "confirm": false
  }
}
```

字段说明：

- `op`：操作类型
  - `"pipeline.delete"` → 删除 pipeline
  - `"pipeline.hotswap"` → 模型热切换
  - `"pipeline.drain"` → drain pipeline
- `mode`：操作模式
  - `"plan"`：只生成计划，不执行
  - `"execute"`：执行操作（需 `confirm=true`）
- `params`：
  - `pipeline_name`：目标 pipeline 名称
  - `node`：hotswap 使用的节点名称
  - `model_uri`：hotswap 使用的新模型 URI
  - `timeout_sec`：drain 超时时间（秒，可选）
- `confirm`：
  - `mode="plan"` 时忽略；
  - `mode="execute"` 且 `confirm=true` 时才允许执行高危操作。

**约定**：前端在删除 / hotswap / drain 时，必须显式设置 `control`，不能依赖 LLM 自由发挥。

---

## 2. 响应结构（control_result）

在现有响应基础上新增 `control_result` 字段：

```json
{
  "message": {
    "role": "assistant",
    "content": "计划删除 pipeline 'cam_01'，请确认后再执行。"
  },
  "control_result": {
    "op": "pipeline.delete",
    "mode": "plan",
    "success": true,
    "plan": {
      "pipeline_name": "cam_01",
      "found": true,
      "plan": {
        "action": "delete",
        "graph_id": "graph_ocsort",
        "default_model_id": "model_v1"
      }
    },
    "result": null,
    "error": null
  },
  "raw_state": {
    "...": "（仅调试用，可忽略）"
  }
}
```

字段说明：

- `message`：自然语言总结，用于聊天区展示。
- `control_result`：前端用于驱动 UI 的结构化数据：
  - `op` / `mode`：回显请求。
  - `success`：控制操作是否成功（计划生成或执行是否成功）。
  - `plan`：对应 `plan_*` 工具的返回值。
  - `result`：仅在 `mode="execute"` 时存在，对应执行工具返回的 HTTP 状态码和 payload。
  - `error`：失败时的错误信息。

---

## 3. 三种典型操作的时序

### 3.1 删除 pipeline（pipeline.delete）

1. **Plan**
   - 请求：`op=pipeline.delete, mode=plan, confirm=false`
   - Agent：调用 `plan_delete_pipeline`，返回 plan（graph_id/default_model_id 等）
   - 前端：展示“将删除 pipeline cam_01 …”，提供“确认删除”按钮
2. **Execute**
   - 请求：`op=pipeline.delete, mode=execute, confirm=true`
   - Agent：先重新调用 `plan_delete_pipeline` 校验目标，再调用 `delete_pipeline(confirm=true, …)`
   - 前端：根据 `control_result.result.status_code` 展示“删除已接受/失败”

### 3.2 模型热切换（pipeline.hotswap）

1. **Plan**
   - 请求：`op=pipeline.hotswap, mode=plan`
   - Agent：调用 `plan_hotswap_model`，返回 `{pipeline_name,node,model_uri}` 计划
   - 前端：展示变更说明与风险提示（显存/兼容性），提供“确认切换”按钮
2. **Execute**
   - 请求：`op=pipeline.hotswap, mode=execute, confirm=true`
   - Agent：调用 `hotswap_model(confirm=true, …)`，返回执行结果

### 3.3 Drain（pipeline.drain）

1. **Plan**
   - 请求：`op=pipeline.drain, mode=plan`
   - Agent：调用 `plan_drain_pipeline`，返回 drain 计划与当前 phase/metrics
   - 前端：展示当前运行状态和 drain 影响说明
2. **Execute**
   - 请求：`op=pipeline.drain, mode=execute, confirm=true`
   - Agent：调用 `drain_pipeline(confirm=true, …)`，返回执行结果

---

## 4. 前端实现建议

- Chat 区：直接展示 `message.content`。
- 控制面板：
  - 根据 `control_result.op` / `mode` / `plan` 渲染删除/切换/drain 的计划表格和 diff；
  - 只有在 `mode=plan & success=true` 时展示“确认”按钮；
  - 点击确认后再发起 `mode=execute & confirm=true` 请求。
- 审计与回放：
  - 建议将 `thread_id` 与具体摄像头/任务绑定，例如 `thread_id=pipeline:cam_01`；
  - 便于在前端按 pipeline 维度查看历史计划与执行记录。

