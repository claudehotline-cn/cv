## MCP 接入草案（TC4）

本草案对应 `openagent_integration_tasks.md` 中 Phase C-TC4 任务：**设计 MCP 接入草案（接口定义与部署拓扑），暂不落地实现**。目标是在不打乱现有 CP/Agent 架构的前提下，为后续引入 MCP 动态工具预留清晰路径。

---

## 1. 目标与约束

- 目标：
  - 在 CV 项目中复用 openAgent 的 MCP 思路，将“外部资源访问能力”封装为独立的 MCP 服务；
  - Agent 通过 MCP 获取动态工具（如 MySQL 查询、Prometheus 指标查询），按需加载；
  - 保持控制面安全：**业务配置仍只能通过 CP API 修改**，MCP 不直接写入业务数据库。
- 约束：
  - 现阶段仅设计，不改动现有 Agent 行为；
  - MCP 主要用于 **只读场景**（查询/取证/诊断），写操作必须经过 CP；
  - 不与 openAgent 的账号体系耦合，仅复用其 MCP Server 设计思路。

---

## 2. 拓扑与部署建议

### 2.1 组件角色

- `cv-agent`：现有 Agent 服务，负责 LangGraph 编排与 CP/VA 控制。
- `cv-mcp`（新服务，后续实现）：MCP HTTP 服务，统一对接外部数据源，暴露工具接口。
- 外部资源：
  - MySQL / PostgreSQL：运维相关只读查询（如统计、历史记录等）；
  - Prometheus / Loki 等：指标与日志查询；
  - 其他 HTTP API：如告警系统、工单系统（中长期）。

### 2.2 Docker / 网络拓扑

- 所有服务加入同一 Docker 网络（如 `cv_net`）：
  - `agent`：`http://agent:8000`
  - `cp-spring`：`http://cp-spring:18080`
  - `mcp`：`http://mcp:8001`
- 仅通过环境变量暴露 MCP 地址给 Agent：
  - `AGENT_MCP_BASE_URL=http://mcp:8001`
  - `AGENT_MCP_TIMEOUT=5s` / `AGENT_MCP_MAX_TOOLS=16` 等。

---

## 3. Agent 与 MCP 的接口约定

### 3.1 MCP 工具抽象

- MCP 服务对外暴露统一 HTTP API，例如：
  - `GET /tools`：列出可用工具及其元数据（名称、描述、输入 schema、只读/高危标签等）；
  - `POST /tools/{name}/invoke`：执行指定工具，输入/输出均为 JSON。
- 工具示例：
  - `mysql.query`（只读）：执行预设 SQL 模板，支持参数化（避免任意 SQL）；
  - `postgres.query`（只读）：类似；
  - `prometheus.query`：执行 PromQL 查询，带采样时间范围与速率限制；
  - `logs.search`：通过 Loki/Elastic 等检索日志。

### 3.2 Agent 侧动态工具加载流程

1. Agent 启动时：
   - 根据 `AGENT_MCP_BASE_URL` 决定是否启用 MCP；
   - 若启用，调用 MCP 的 `GET /tools` 获取工具列表；
   - 将这些工具以“远程工具包装器”的形式注册到 `ToolRegistry`，领域标记为 `domain="mcp"`。
2. 工具调用时：
   - LangGraph 产生 `tool_calls`（name + args）；
   - ToolExecutor 发现属于 `domain="mcp"` 的工具时：
     - 将调用转发到 MCP：`POST /tools/{name}/invoke`；
     - 超时/错误时返回结构化错误信息，并在 Agent 日志中打点。
3. 安全与配额：
   - MCP 侧实现认证/鉴权（如通过内部 token），确保仅 Agent 可访问；
   - 为每个工具配置限流与超时，避免大模型生成的异常调用拖垮后端。

---

## 4. 与 ToolRegistry 的集成方案

在现有 `agent/cv_agent/tools/registry.py` 基础上，扩展支持 MCP 工具元数据：

- 新增字段：
  - `origin: "local" | "mcp"`：标识工具来源；
  - `mcp_tool_name`：对应 MCP 内部工具名（可与本地 name 不同）。
- Agent 启动时新增一个初始化步骤：

```python
# 伪代码：在 cv_agent.tools.__init__ 之后执行
from .registry import register_tool
from .mcp import load_mcp_tools

for meta in load_mcp_tools():
    register_tool(
        meta.to_langchain_tool(),
        name=meta.name,
        read_only=meta.read_only,
        high_risk=meta.high_risk,
        domain="mcp",
    )
```

- `load_mcp_tools()` 负责：
  - 调用 MCP `/tools` 接口；
  - 将返回的工具描述转换为 LangChain Tool 对象；
  - 对高危工具（如可能写库的操作）默认置为禁用或 require confirm。

---

## 5. 渐进式落地路径

1. **PoC 阶段（只读、单一数据源）**
   - 在独立 repo 或 `third-party` 下基于 openAgent MCP 示例实现最小 MCP 服务（仅 MySQL/Prometheus 只读）；
   - Agent 侧实现 `load_mcp_tools()` 与远程调用包装；
   - 在实验性 StateGraph 入口（如 `/v1/agent/stategraph/threads/{thread_id}/invoke`）中启用 MCP 工具，验证行为。
2. **灰度阶段（扩展数据源与监控）**
   - 将更多运维相关数据源（日志/告警）接入 MCP；
   - 为每类 MCP 工具定义明确的使用场景与文档；
   - 在 Grafana 中增加 Agent→MCP 调用的指标与告警。
3. **稳定阶段（文档与规范）**
   - 将 MCP 工具纳入 `docs/plans/openagent_integration_tasks.md` 的后续阶段任务；
   - 在 Agent 使用文档中明确说明哪些能力通过 MCP 提供、哪些仍由 CP/VA 完成；
   - 如需引入写操作（例如运维工具自动修复），必须先设计专门的安全/审计方案，并通过 plan→execute 流程保护。

---

## 6. 不在本轮 MCP 设计范围内的内容

- 复杂多租户隔离与细粒度权限管理（可在 MCP 后续版本按需引入）；
- 通过 MCP 直接修改业务数据库的能力（与当前“CP 是唯一真相源”的原则冲突）；
- 将 Agent 变为通用数据库工作台或 BI 工具（超出本项目控制与运维助手的定位）。

