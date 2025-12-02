1. Agent 工具层完善（P0）
1.1 工具包总体结构设计

1.1.1 确定 cv_agent/tools 包目录结构

1.1.2 定义 get_all_tools(settings) 的对外接口约定

1.1.3 识别当前 CP 需要暴露的全部工具列表（pipelines、rag、后续 train 等）

1.2 Pipeline 管理工具实现

1.2.1 新建 cv_agent/tools/pipelines.py

1.2.2 把已有 _fetch_pipelines / _fetch_pipeline_status 封装为内部函数

1.2.3 封装 pipeline.delete Tool（含输入/输出 Pydantic 模型）

1.2.4 封装 pipeline.hotswap Tool（支持 model_uri / version）

1.2.5 封装 pipeline.drain Tool（支持 timeout 等参数）

1.2.6 在 get_all_tools() 中注册上述 Tool

1.3 RAG 工具实现

1.3.1 新建 cv_agent/tools/rag.py

1.3.2 定义 SearchCvDocsInput Pydantic 模型（关键字/模块/top_k 等）

1.3.3 封装 search_cv_docs_tool（基于 rag/pg_store.py）

1.3.4 在 get_all_tools() 中注册 RAG Tool

1.4 工具层联调 & 修复引用

1.4.1 修正 cv_agent/graph/control_plane.py 中对 get_all_tools 的引用

1.4.2 修正 cv_agent/graph/control_plane.py 中对 search_cv_docs_tool 的引用

1.4.3 修正 cv_agent/server/api.py 中对于 pipelines 工具的 import

1.4.4 本地启动 Agent 服务，验证工具可被 Agent 调用

2. StateGraph 主路径化 & 调用流程梳理（P0）
2.1 StateGraph 结构确认

2.1.1 复查 _build_stategraph_agent() 中各节点（router/rag/agent/tools）

2.1.2 检查有无潜在循环和不必要边

2.1.3 明确 AgentState.task 的枚举值和含义（pipeline/debug/model/…）

2.2 API 与 StateGraph 绑定

2.2.1 将 invoke_agent() 主路径改为调用 _invoke_stategraph_agent()

2.2.2 将 invoke_agent_thread() 主路径改为调用 _invoke_stategraph_agent()

2.2.3 保留 invoke_stategraph_thread() 作为显式 StateGraph 调用入口（如需要）

2.3 ReAct Agent 降级为兼容模式

2.3.1 在 _build_agent()（ReAct）增加注释：仅用于兼容/回退

2.3.2 在 _invoke_stategraph_agent() 中实现：

openai 且无 api_key 时 fallback 到 _invoke_agent_graph()

2.3.3 文档中注明未来新功能只挂 StateGraph，不再扩展 ReAct Agent

3. Checkpoint 持久化（P0）
3.1 Sqlite Checkpoint 接入

3.1.1 在 cv_agent/store/checkpoint.py 中完善 SqliteSaver 创建逻辑

3.1.2 支持通过 env 配置 sqlite 文件路径（如 /data/agent/checkpoints.db）

3.1.3 为 sqlite 后端增加初始 schema 初始化逻辑（如需要）

3.2 部署配置

3.2.1 在 docker-compose / k8s 中为 Agent 容器挂载持久化卷

3.2.2 配置 AGENT_CHECKPOINT_BACKEND=sqlite 及路径 env

3.2.3 验证容器重启后，线程状态和对话可恢复

3.3 多并发线程验证

3.3.1 脚本压测不同 thread_id 并发调用

3.3.2 确认各线程状态隔离 & 互不覆盖

3.3.3 记录发现的问题并修复

4. 权限控制与多租户基础（P1）
4.1 权限模型定义

4.1.1 分析现有 UserContext（user_id/role/tenant）字段

4.1.2 确定初版角色定义（如 admin、operator、viewer）

4.1.3 定义角色到操作（op）的权限矩阵（pipeline.delete/hotswap/drain）

4.2 API 层权限检查实现

4.2.1 在 cv_agent/server/api.py 实现 _check_permission(user, op)

4.2.2 在 _handle_control() 开头插入权限校验逻辑

4.2.3 为无权限场景返回统一错误码/错误消息

4.3 多租户约束接入

4.3.1 在调用 CP HTTP 接口时传递 tenant 信息

4.3.2 配合 CP 侧校验 pipeline 是否属于该 tenant

4.3.3 在错误信息中清晰提示“跨租户访问被拒绝”

5. 控制协议与 Tool 抽象统一（P1）
5.1 ControlRequest 和 Tool 的映射设计

5.1.1 设计 ControlRequest.op → Tool 名称的映射关系

5.1.2 定义 Tool 输入/输出与 ControlParams/ControlResult 的映射逻辑

5.1.3 文档化这套映射规则

5.2 _handle_control() 重构

5.2.1 去除 _handle_control() 中对 _call_* 的直接依赖

5.2.2 改为通过 pipelines Tool 的统一接口进行调用

5.2.3 保留 plan/execute/confirm 语义（在 Tool 调用前后构造 ControlResult）

5.3 统一审计与统计

5.3.1 让所有 Tool 调用都通过同一统计通道记录（成功/失败/耗时）

5.3.2 将 _AGENT_STATS 与 Tool 维度统计打通

5.3.3 预留将来接 Prometheus/日志系统的接口

6. Agent 数据结构 & 前端展示契约（P1）
6.1 agent_data JSON Schema 设计

6.1.1 确定 agent_data 的顶层结构（如 steps 列表）

6.1.2 定义 step 类型：thought / tool_call / response / error 等

6.1.3 在 AgentInvokeResponse 中固定该 schema

6.2 线程摘要结构完善

6.2.1 在 ThreadSummary 中确保包含：

最后 user 摘要

最后 assistant 摘要

最后 control 操作及结果

6.2.2 更新 update_summary_for_messages() / update_summary_for_control() 逻辑

6.2.3 确保 /threads、/summary 返回的数据结构稳定

6.3 Agent UI 约定文档

6.3.1 新建 docs/design/agent-ui.md

6.3.2 描述前端如何使用 /threads /summary /stats + agent_data

6.3.3 约定时间线展示形式、字段含义、错误展示方式

7. RAG 流程增强（P1）
7.1 PG 存储层增强

7.1.1 在 rag/pg_store.py 使用 Settings 统一配置 DSN

7.1.2 增加按模块/文档类型查询能力

7.1.3 增加基础异常处理和重试机制

7.2 文档导入流程优化

7.2.1 为 rag/ingest_docs.py 增加 CLI 参数（docs 根目录/模块标签）

7.2.2 增加去重逻辑，避免重复导入同一个文档版本

7.2.3 在 ingest 时记录 metadata（文件路径、更新时间、模块）

7.3 与 Tool 的集成验证

7.3.1 使用 search_cv_docs_tool 对项目 docs 做端到端查询测试

7.3.2 调整 prompt 模板，让 Agent 知道何时优先调用 RAG

7.3.3 记录典型问答样例，便于回归测试

8. 测试与质量保障（P2）
8.1 测试框架与目录搭建

8.1.1 新建 agent/tests/ 目录

8.1.2 配置 pytest 基础环境（依赖、配置文件）

8.1.3 引入简单的 test utilities（如 mock CP HTTP）

8.2 核心功能单元测试

8.2.1 Router 任务分流测试（不同输入 → 不同 task）

8.2.2 Control plan/execute/confirm 流程测试

8.2.3 RAG 工具查询正确性测试

8.3 异常与回退路径测试

8.3.1 GraphRecursionError 场景测试

8.3.2 INVALID_CHAT_HISTORY 自动重建 thread 测试

8.3.3 无 openai key 时的本地离线模式测试

9. 日志与可观测性（P2）
9.1 HTTP 层日志

9.1.1 在中间件记录每次请求的 thread_id/user_id/op/mode/耗时

9.1.2 区分成功/失败/异常情况

9.1.3 确保日志格式适配现有 log 收集方案

9.2 Agent 层指标

9.2.1 为每个 Tool 调用记录耗时和状态

9.2.2 为每个 Control op 记录次数/成功率

9.2.3 预留 Prometheus metrics（如 qps、error_rate、latency）

10. 多 Agent 拆分与高级演进（P3）
10.1 多 Agent 拆分设计

10.1.1 设计 Pipeline Agent / Debug Agent / Model Agent 职责

10.1.2 设计 Router 将请求分派到不同子 Agent 的策略

10.1.3 在文档中记录这些 Agent 的边界与交互

10.2 StateGraph 中落地多 Agent

10.2.1 在 StateGraph 中为不同 Agent 创建子图或子节点

10.2.2 确保不同 Agent 共享同一个 AgentState 或设计必要的转换

10.2.3 回归测试多 Agent 下的任务路由与工具调用

11. 高级 Checkpoint 后端（可选，P3）
11.1 MySQL Checkpoint 设计

11.1.1 设计 agent_checkpoints 表结构（thread_id + state + version/timestamps）

11.1.2 设计基本的 CRUD 接口与索引策略

11.1.3 评估与当前 MySQL 实例的资源影响

11.2 MySQL Checkpoint 实现与切换

11.2.1 在 cv_agent/store/checkpoint.py 中新增 MySQL 后端实现

11.2.2 通过 env 切换 sqlite / mysql

11.2.3 多实例部署验证状态共享