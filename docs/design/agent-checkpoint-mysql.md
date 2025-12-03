# Agent MySQL Checkpoint 设计（P3）

本文档对应 `agent_tasks` / `agent_wbs` 中的「11. 高级 Checkpoint 后端（可选，P3)」：在已有内存与 SQLite checkpoint 的基础上，为 Python `cv_agent` 提供一个基于 MySQL 的 checkpoint 后端，以支持多实例共享线程状态。当前版本中，MySQL 后端已经在 `cv_agent` 内实现并可用于生产部署，默认仍以 SQLite 为主。

## 1. 目标与约束

- 目标：
  - 为 `cv_agent` 提供一个可选的 MySQL checkpoint 后端，在多实例部署场景下共享 LangGraph 线程状态；
  - 保持与现有 `MemorySaver` / `SqliteSaver` 相同的调用方式，仍通过 `get_checkpointer()` 返回统一接口对象；
  - 通过 `AGENT_CHECKPOINT_BACKEND=mysql` + `AGENT_CHECKPOINT_MYSQL_DSN` 环境变量完成切换。
- 约束：
  - 当前版本仍以 SQLite 为默认持久化方案，MySQL 后端为 P3 选项，可按需启用；
  - MySQL 连接使用 `pymysql`，不引入 ORM，保持实现轻量级；
  - 为便于迁移，checkpoint 的内部结构尽量复用 LangGraph 的 `Checkpoint` / `CheckpointMetadata` 定义。

## 2. 表结构设计

### 2.1 `agent_checkpoints` 表

参考 LangGraph CheckpointSaver 对 `thread_id` / `checkpoint` 的抽象，设计一张统一表（已在 `db/schema.sql` 中创建）：

```sql
CREATE TABLE IF NOT EXISTS agent_checkpoints (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  thread_id     VARCHAR(255) NOT NULL,
  checkpoint_ns VARCHAR(255) NOT NULL,
  -- LangGraph 的 checkpoint 通常包含消息状态、config 等信息，这里统一存 JSON
  checkpoint    JSON NOT NULL,
  -- 可选版本号，用于乐观锁或回滚（预留，初期可固定为 1）
  version       INT NOT NULL DEFAULT 1,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  -- 复合索引：按 thread_id + namespace 查询最近一次 checkpoint
  INDEX idx_agent_chk_thread_ns (thread_id, checkpoint_ns),
  INDEX idx_agent_chk_updated   (updated_at),
  CHECK (JSON_VALID(`checkpoint`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
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
  `mysql+pymysql://root:123456@mysql:3306/cv_cp`。

在 Docker 部署中，可在 `docker/compose/docker-compose.yml` 的 `agent` 服务中切换环境变量：

```yaml
environment:
  # 默认：使用 SQLite checkpoint（挂载到持久化卷）
  - AGENT_CHECKPOINT_BACKEND=sqlite
  - AGENT_CHECKPOINT_SQLITE_CONN=/data/checkpoints/checkpoints.sqlite

  # 如需在多实例部署中共享线程状态，可改为：
  # - AGENT_CHECKPOINT_BACKEND=mysql
  # - AGENT_CHECKPOINT_MYSQL_DSN=mysql+pymysql://root:123456@mysql:3306/cv_cp
```

注意：

- 示例 DSN 中默认使用 `cv_cp` 数据库（与 ControlPlane 共用实例），`db/schema.sql` 中的 `agent_checkpoints` 表也建在该库下；
- 若需要单独的 Agent 库，可在 MySQL 中手工创建数据库并相应调整 DSN。

## 4. `get_checkpointer()` 中的 MySQL 分支

`agent/cv_agent/store/checkpoint.py` 已根据 `AGENT_CHECKPOINT_BACKEND` 切换 backend：

- `memory` → `MemorySaver()`；
- `sqlite` → `SqliteSaver.from_conn_string(conn_str)`（依赖 `langgraph-checkpoint-sqlite`）；
- `mysql` → 使用 `cv_agent/store/checkpoint_mysql.MySQLSaver.from_dsn(dsn)` 读写 `agent_checkpoints`。

MySQL 实现遵循 LangGraph `BaseCheckpointSaver` 接口的最小子集：

- 按 `(thread_id, checkpoint_ns)` 维度仅保存“最新”一个 checkpoint（不保留历史版本），满足多副本共享线程状态的需求；
- 将 `Checkpoint` / `CheckpointMetadata` / pending writes 通过 LangGraph 自带的 `JsonPlusSerializer` 编码为 `{type, b64}` 结构，并整体作为 JSON 写入 `checkpoint` 字段；
- 提供同步/异步的 `get_tuple` / `put` / `put_writes` 以及 `aget_tuple` / `aput` / `aput_writes`，使其可直接作为 `create_react_agent` 和 `StateGraph` 的 checkpointer。

当 `AGENT_CHECKPOINT_BACKEND=mysql` 且 `AGENT_CHECKPOINT_MYSQL_DSN` 配置错误或连接失败时，`get_checkpointer()` 会记录 warning 并自动回退到 `MemorySaver`，避免影响主流程。

## 5. 实现状态与多实例部署建议

### 5.1 当前实现状态

- `db/schema.sql` 已创建 `agent_checkpoints` 表；
- `agent/cv_agent/store/checkpoint_mysql.py` 实现了基于 MySQL 的 `MySQLSaver`（继承 LangGraph 的 `BaseCheckpointSaver`）；
- `agent/cv_agent/store/checkpoint.py` 已接入 `mysql` 分支，并在配置缺失或失败时回退到内存模式；
- `docker/compose/docker-compose.yml` 中的 `agent` 服务默认仍使用 SQLite，通过注释给出了 MySQL 切换示例；
- `agent/requirements.txt` 中已加入 `pymysql` 依赖。

### 5.2 多实例部署（Docker Compose 示例）

在当前 `docker/compose/docker-compose.yml` 基础上，可以通过环境变量切换到 MySQL checkpoint，并扩容 `agent` 副本来共享线程状态：

1. 在 `agent` 服务中启用 MySQL：

   ```yaml
   services:
     agent:
       environment:
         - AGENT_CHECKPOINT_BACKEND=mysql
         - AGENT_CHECKPOINT_MYSQL_DSN=mysql+pymysql://root:123456@mysql:3306/cv_cp
   ```

2. 启动多副本（示例）：

   ```bash
   cd docker/compose
   docker compose up -d --scale agent=2
   ```

3. 验证线程共享：

   - 在副本 A 上调用 `POST /v1/agent/threads/{thread_id}/invoke` 多轮对话；
   - 停止或重启 A，再用同一个 `{thread_id}` 命中副本 B（例如通过负载均衡或手工访问另一个容器）；
   - 预期：对话能在 B 上延续，说明 checkpoint 已从 MySQL 恢复。

在生产环境中，可按上述思路接入负载均衡 / Service Mesh，将多个 `cv_agent` 副本挂在同一个 MySQL 实例上，即可实现“不同 Agent 副本共享线程状态”。***
