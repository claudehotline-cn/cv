## Agent 服务 WBS（按阶段与模块分解）

### 1. 项目启动与范围定义

- 1.1 明确 agent 目标与边界（仅通过 CP 操作，不直接写业务库）
- 1.2 梳理角色与权限模型（user/role/tenant 与 CP 权限映射）
- 1.3 定义成功指标（典型用例覆盖度、响应时间、操作准确率等）

### 2. 环境与依赖管理

- 2.1 确认运行环境（Python 版本、部署方式：Docker/K8s）
- 2.2 确认并锁定依赖版本（langchain/langgraph/langgraph-prebuilt/langchain-openai/fastapi 等）
- 2.3 规划配置管理方案（环境变量、.env、pydantic-settings）

### 3. CP / VA / 监控接口梳理

- 3.1 整理 CP API：pipeline CRUD、模型/追踪配置、状态查询
- 3.2 整理 VA 状态接口（如有）：任务状态、告警等
- 3.3 整理监控指标来源：Prometheus / CP 代理
- 3.4 输出统一接口契约文档（路径、参数、错误码、超时策略）

### 4. Agent 服务骨架与目录结构

- 4.1 创建 `agent/cv_agent` 模块及基础目录结构（config/tools/graph/server/store）
- 4.2 实现 `config.py`（Pydantic Settings + 环境变量）
- 4.3 搭建 FastAPI 基础应用与健康检查接口

### 5. Tools 设计与实现

- 5.1 设计工具分层与命名规范（list/get/create/update/toggle 等）
- 5.2 实现只读类 CP 工具（list_pipelines/get_pipeline_status/get_pipeline_config 等）
- 5.3 实现监控工具（get_pipeline_metrics/get_gpu_metrics 等）
- 5.4 规划写操作工具（create_pipeline/update_pipeline_config/toggle_ocsort_gpu 等），设计 dry-run + diff 输出

### 6. LangGraph / Agent 编排

- 6.1 Phase1：使用 `create_react_agent` + 工具集构建单 ReAct Agent MVP
- 6.2 Phase2：引入持久化 checkpoint（SQLite/MySQL），支持 thread_id 多轮对话
- 6.3 Phase3：基于 `StateGraph` 拆分 Router/PipelineAgent/DebugAgent/ModelAgent 等多 Agent

### 7. 安全、权限与人机协同

- 7.1 设计身份透传机制（X-User-Id/X-User-Role/X-Tenant）并注入 LangGraph state
- 7.2 明确高危操作列表（删除、批量更新、切模型等）
- 7.3 设计并实现 dry-run + diff + interrupt + resume 的人机协同流程
- 7.4 与 CP 协同定义审计字段和记录规范

### 8. HTTP API 与前端集成

- 8.1 设计 `/v1/agent/invoke` 请求/响应协议（包含 messages、thread_id、meta 信息）
- 8.2 设计 `/v1/agent/threads/{thread_id}/invoke` 多轮接口（Phase2）
- 8.3 前端接入：基础对话界面、错误提示、人机协同确认 UI
- 8.4 与现有 CP 前端交互模式对齐（避免引入新的权限入口）

### 9. 部署与运维

- 9.1 编写 Dockerfile / `docker-compose.agent.yml`，接入现有网络（如 `cv-net`）
- 9.2 定义环境变量与运行参数（端口、下游地址、日志级别等）
- 9.3 接入监控与告警（接口 QPS、错误率、工具调用情况）
- 9.4 制定上线与回滚方案（agent 宕机不影响 VA/CP）

### 10. 可观测性、日志与审计

- 10.1 设计日志结构（request_id/thread_id/user_id/tool_name/结果摘要）
- 10.2 与 CP 侧审计打通：标记“由 agent 触发”的操作
- 10.3 视情况接入 LangSmith 或内部 trace 方案做调试
- 10.4 制定日志保留与隐私策略

### 11. 文档与培训

- 11.1 编写 README / 接口文档 / 使用示例
- 11.2 补充 `docs/` 下 agent 相关设计与运维说明
- 11.3 编写常见问题（FAQ）与排障指南
- 11.4 验收后组织内部分享或小范围培训

