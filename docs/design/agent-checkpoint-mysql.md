# Agent MySQL Checkpoint 设计（P3 草案）

本文档对应 `agent_tasks` / `agent_wbs` 中的「11. 高级 Checkpoint 后端（可选，P3)」：在已有内存与 SQLite checkpoint 的基础上，为 Python `cv_agent` 规划一个基于 MySQL 的 checkpoint 后端，以支持多实例共享线程状态。当前阶段以**设计与接口占位**为主，实际接入 MySQL checkpointer 将在后续迭代中落地。

## 1. 目标与约束

- 目标：
  - 为 `cv_agent` 提供一个可选的 MySQL checkpoint 后端，在多实例部署场景下共享 LangGraph 线程状态；
  - 保持与现有 `MemorySaver` / `SqliteSaver` 相同的调用方式，仍通过 `get_checkpointer()` 返回统一接口对象；
  - 通过 `AGENT_CHECKPOINT_BACKEND=mysql` + `AGENT_CHECKPOINT_MYSQL_DSN` 环境变量完成切换。
- 约束：
  - 当前版本仍以 SQLite 为默认持久化方案，MySQL 后端为 P3 选项，短期内不作为强依赖；
  - 仓库中先提供表结构与接口设计，占位实现仍抛出清晰错误，避免误用未完成的后端；
  - MySQL 连接建议使用 `pymysql`（项目中已有相关依赖与使用经验）。

## 2. 表结构设计

### 2.1 `agent_checkpoints` 表

参考 LangGraph CheckpointSaver 对 `thread_id` / `checkpoint` 的抽象，设计一张统一表：

```sql
CREATE TABLE IF NOT EXISTS agent_checkpoints (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  thread_id     VARCHAR(255) NOT NULL,
  checkpoint_ns VARCHAR(255) NOT NULL,
  -- LangGraph 的 checkpoint 通常包含消息状态、config 等信息，这里统一存 JSON
  checkpoint    JSON NOT NULL,
  -- 可选版本号，用于乐观锁或回滚（预留，初期可固定为 1）
  version       INT NOT NULL DEFAULT 1,
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  -- 复合索引：按 thread_id + namespace 查询最近一次 checkpoint
  INDEX idx_thread_ns (thread_id, checkpoint_ns),
  INDEX idx_updated   (updated_at)
);
```

字段说明：

- `thread_id`：LangGraph config 中的 thread 唯一标识，对应 HTTP 层的 `{thread_id}` 路径参数；
- `checkpoint_ns`：命名空间，用于区分不同 Graph 或用途的 checkpoint（与 SQLite Saver 的命名空间理念一致）；
- `checkpoint`：完整的 checkpoint 状态 JSON（内部结构由 LangGraph 生成与解析）；
- `version`：预留字段，便于未来实现多版本与回滚策略；
- `created_at/updated_at`：用于调试与监控。

## 3. 配置与切换

在 `agent/cv_agent/config.py` 中已预留：

- `AGENT_CHECKPOINT_BACKEND`：`memory` / `sqlite` / `mysql`；
- `AGENT_CHECKPOINT_MYSQL_DSN`：MySQL DSN 字符串，例如  
  `mysql+pymysql://root:123456@mysql:3306/cv_agent`。

在 Docker 部署中，可在 `docker/compose/docker-compose.yml` 的 `agent` 服务中追加：

```yaml
environment:
  - AGENT_CHECKPOINT_BACKEND=mysql
  - AGENT_CHECKPOINT_MYSQL_DSN=mysql+pymysql://root:123456@mysql:3306/cv_agent
```

当前代码仍保持 `backend=mysql` 分支抛出异常，避免误用未实现后端；实际切换需在完成 MySQLSaver 实现后再启用上述配置。

## 4. `get_checkpointer()` 中的 MySQL 占位分支

`agent/cv_agent/store/checkpoint.py` 已根据 `AGENT_CHECKPOINT_BACKEND` 切换 backend：

- `memory` → `MemorySaver()`；
- `sqlite` → `SqliteSaver.from_conn_string(conn_str)`（依赖 `langgraph-checkpoint-sqlite`）；
- `mysql` → 当前版本抛出 `RuntimeError`，提示尚未实现。

后续接入 MySQL 时，建议按以下步骤演进：

1. **实现 MySQLSaver（建议独立模块）**  
   - 新增 `cv_agent/store/checkpoint_mysql.py`，实现一个满足 LangGraph CheckpointSaver 接口的 `MySQLSaver`：
     - 使用 `pymysql` 或 SQLAlchemy 建立连接池；
     - 按 `thread_id + checkpoint_ns` 维度实现 `get/put/list` 等必要方法；
     - 内部读写 `agent_checkpoints` 表，使用 JSON 字段存储 checkpoint。
2. **在 `get_checkpointer()` 中接入**  
   - 当 `backend == "mysql"` 时，构造 `MySQLSaver` 实例并返回；
   - 遇到导入或连接错误时，记录 warning 并可选回退到 `MemorySaver`（需在日志中明确提示）。
3. **验证与回归**  
   - 在 dev 环境中部署一个独立的 `cv_agent` 实例，开启 MySQL checkpoint，并通过：
     - 多次重启 Agent 容器验证 thread 状态可从 MySQL 恢复；
     - 多实例部署下，通过相同 `thread_id` 访问不同 Agent 副本，确认状态共享无异常。

## 5. 实现状态说明

- 当前仓库：
  - 已有配置字段与 MySQL backend 分支占位；
  - 尚未引入 MySQLSaver 实现，也未在 `agent/requirements.txt` 中增加 MySQL 驱动依赖。
- 本文档作为 P3 设计草案，为后续实现提供：
  - 表结构与索引策略；
  - 配置方式与切换路径；
  - 与 LangGraph CheckpointSaver 接口对齐的设计思路。

在正式引入 MySQLSaver 之前，**请勿**在生产环境设置 `AGENT_CHECKPOINT_BACKEND=mysql`，否则 Agent 会在启动时抛出异常。

