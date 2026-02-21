# Agent Platform 架构设计 (Final)

## 实施状态

| Phase | 状态 | 说明 |
|-------|------|------|
| Phase 1: 核心框架 | ✅ 完成 | agent-core, agent-plugins, agent-platform-api |
| Phase 2: 异步执行 | 🔲 待开始 | Redis + ARQ |
| Phase 3: 前端适配 | 🔲 待开始 | agent-chat-vue |
| Phase 4: 测试框架 | 🔲 待开始 | agentevals + pytest |

---

## 项目结构 (实际)

```
/home/chaisen/projects/cv/
├── agent-core/                    # 核心 SDK
│   └── agent_core/
│       ├── base.py, runtime.py, settings.py
│       ├── state.py, middleware.py, store.py
│
├── agent-plugins/                 # 业务插件
│   └── data_agent/                # ✅ 已迁移
│       ├── graph.py, schemas.py, prompts.py
│       ├── tools/, subagents/, utils/
│
├── agent-platform-api/            # 统一 API
│   └── app/
│       ├── main.py, db.py, worker.py
│       ├── core/, models/, routes/
│
├── article_agent/                 # [待迁移] → agent-plugins
└── rag_service/                   # [独立] RAG 服务
```

---

## 数据库 Schema (PostgreSQL)

```sql
CREATE TABLE agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type VARCHAR(20) NOT NULL,  -- 'builtin' | 'custom'
    builtin_key VARCHAR(50),
    config JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES agents(id),
    title VARCHAR(200),
    state JSONB,
    is_interrupted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id),
    role VARCHAR(20) NOT NULL,
    content TEXT,
    thinking TEXT,
    tool_calls JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Agent 配置项 (JSONB)

```json
{
  "system_prompt": "你是一个...",
  "llm": {"provider": "vllm", "model": "qwen3:30b"},
  "tools": ["sql_query", "python_exec"],
  "retrieval": {"enabled": true, "collection": "kb", "top_k": 5}
}
```

---

## 高级架构设计

### 1. 插件系统 (Plugin System)

**发现机制：entry_points + 配置过滤（混合模式）**

```toml
# data_agent/pyproject.toml
[project.entry-points."agent_plugins"]
data_agent = "data_agent:DataAgent"
```

```python
# settings.py
enabled_agents: list[str] = []   # 空=全部加载，非空=白名单
disabled_agents: list[str] = []  # 黑名单排除
```

**加载逻辑：**
1. 从 entry_points 发现所有 `agent_plugins` 组的插件
2. 白名单过滤：`enabled_agents` 非空时只加载列表中的
3. 黑名单排除：跳过 `disabled_agents` 中的插件

**优势：** 自动发现 + 选择控制 + 环境变量覆盖

### 2. 异步任务队列
- Redis + ARQ，Worker 进程池
- `/execute` → task_id → Redis Stream → 前端轮询

### 3. 通用状态协议
- API 不感知具体 State 结构，统一 JSONB 透传

### 4. 测试策略 (LangChain Best Practice)

**3 层测试架构：**

| 层级 | 工具 | 用途 |
|------|------|------|
| 单元测试 | `GenericFakeChatModel` + `InMemorySaver` | Mock LLM，避免 API 调用 |
| 集成测试 | `agentevals.trajectory.match` | 验证工具调用轨迹 |
| 质量评估 | LLM-as-Judge | 评估执行质量 |

**Trajectory Match 模式：**
- `strict` - 严格顺序匹配
- `unordered` - 不关心顺序
- `subset/superset` - 子集/超集匹配

```python
# 示例
from agentevals.trajectory.match import create_trajectory_match_evaluator
evaluator = create_trajectory_match_evaluator(trajectory_match_mode="unordered")
```

### 5. Agent 配置器 UI (Configurator)

**功能模块：**

| 模块 | 组件 | 说明 |
|------|------|------|
| 基础信息 | 名称、描述输入框 | Agent 标识 |
| Prompt 编辑器 | Monaco Editor | 支持变量高亮 `{{user_input}}` |
| LLM 配置 | 下拉 + 滑块 | 模型选择、temperature/max_tokens |
| 工具选择 | 多选穿梭框 | 可用工具池 → 启用工具 |
| RAG 配置 | 开关 + 知识库选择 | 关联 rag_service |

**API 端点：**
- `POST /agents` - 创建自定义 Agent
- `PUT /agents/{id}` - 更新配置
- `GET /agents/{id}/config-schema` - 获取配置表单 Schema

**前端路由：** `/settings/agents/new`, `/settings/agents/{id}/edit`

### 6. 版本管理策略 (Versioning)

**DB Schema 扩展：**
```sql
ALTER TABLE agents ADD COLUMN version VARCHAR(20) DEFAULT '1.0.0';
ALTER TABLE sessions ADD COLUMN agent_version VARCHAR(20);
```

**兼容性规则：**
| 变更类型 | 语义版本 | 处理方式 |
|----------|----------|----------|
| 新增可选字段 | PATCH | 向后兼容，无需迁移 |
| 新增必填字段 | MINOR | State 迁移脚本填充默认值 |
| 删除/重命名字段 | MAJOR | 废弃期 + 迁移工具 |

**迁移机制：**
- `agent-plugins/{name}/migrations/` 目录存放迁移脚本
- 启动时自动检测并执行未应用的迁移

---

## 可扩展性评估 (设计层面)

| 维度 | 评分 | 设计分析 |
|------|------|------|
| 插件发现 | ⭐⭐⭐⭐⭐ | entry_points 标准机制 + 白名单/黑名单灵活控制 |
| 多 Agent 隔离 | ⭐⭐⭐⭐⭐ | 独立包、独立 State、零耦合 |
| 水平扩展 | ⭐⭐⭐⭐⭐ | ARQ Worker replicas + Redis 解耦 |
| 添加新 Agent | ⭐⭐⭐⭐⭐ | 实现 BaseAgent + 注册 entry_point 即可 |
| 自定义 Agent | ⭐⭐⭐⭐⭐ | DB config + UI 配置器设计完成 |
| 多租户 | N/A | 当前单组织，未来可扩展 (添加 tenant_id) |

## 维护性评估 (设计层面)

| 维度 | 评分 | 设计分析 |
|------|------|------|
| 代码复用 | ⭐⭐⭐⭐⭐ | agent-core 抽离共享逻辑 |
| 依赖管理 | ⭐⭐⭐⭐⭐ | 插件仅依赖 core，pyproject.toml 声明式 |
| 配置管理 | ⭐⭐⭐⭐⭐ | Pydantic Settings + ENV 覆盖 |
| 测试策略 | ⭐⭐⭐⭐⭐ | 3 层架构：Mock/Trajectory/LLM-as-Judge |
| 状态透传 | ⭐⭐⭐⭐⭐ | JSONB 通用协议，API 与 Agent 解耦 |
| 版本兼容 | ⭐⭐⭐⭐⭐ | 语义版本 + 迁移脚本机制设计完成 |

---

## 改进建议

1. Logger 命名清理 (`agent_langchain` → `data_agent`)
2. 添加 `tests/` + pytest
3. entry_points 自动发现
4. article_agent 迁移到 agent-plugins

---

## 部署配置

```yaml
services:
  agent-api:
    build: agent-platform-api
    ports: ["18111:8000"]
    volumes:
      - ./agent-core:/app/agent-core:ro
      - ./agent-plugins:/app/agent-plugins:ro

  agent-worker:
    command: ["arq", "app.worker.WorkerSettings"]
```
