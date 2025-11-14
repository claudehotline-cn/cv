# 控制面与 VA 存储访问详细设计（2025-11-14）

## 1 概述

### 1.1 目标

本说明书详细描述控制面（Controlplane）与 Video Analyzer 在存储层面的设计，包括 MySQL 数据库、连接池与仓储（Repo）模式，以及与训练/订阅等业务流程的关系。

### 1.2 范围

- 控制平面（CP）侧：
  - `controlplane/src/server/db.cpp` 及其与配置的关系；
  - 训练任务与模型元数据的读写路径。
- VA 侧：
  - `video-analyzer/src/storage/*` 中的 DbPool 与各 Repo；
  - REST 层与 DB 的交互流程（事件、日志、会话等）。

### 1.3 相关文档

- 概要设计：`docs/design/architecture/整体架构设计.md`
- 数据库 schema：`docs/design/storage/数据库设计.md`
- VA 详细设计：`docs/design/architecture/video_analyzer_详细设计.md`
- Controlplane 设计：`docs/design/architecture/controlplane_design.md`

## 2 数据库设计概览

详细表结构见 `docs/design/storage/数据库设计.md`，本节仅概述关键实体：

- `sources`：视频源（id/uri/status/caps/fps/...）。
- `pipelines`：管线定义（name/graph_id/default_model_id/encoder_cfg/...）。
- `graphs`：graph 元数据与配置文件路径。
- `models`：模型元数据（id/task/family/variant/path/conf/iou/...）。
- `sessions`：订阅会话生命周期（id/stream_id/pipeline/model_id/status/error_msg/...）。
- `events`：业务事件（告警/状态变更等）。
- `logs`：结构化日志。
- 训练相关表（训练任务、工件、部署记录等），细节见数据库设计文档。

## 3 VA 存储访问设计

### 3.1 DbPool 抽象

头文件：`video-analyzer/src/storage/db_pool.hpp`  
实现：`video-analyzer/src/storage/db_pool.cpp`

- `DbPool` 抽象数据库连接池，统一管理连接创建、复用与统计：
  - `static std::shared_ptr<DbPool> create(const AppConfigPayload::DatabaseConfig& cfg)`：
    - 当 driver 为 `mysql` 或相关配置完整时创建真实 `MySqlDbPool`；
    - 否则创建 `NullDbPool`，所有操作为 no-op，保证 VA 在无 DB 环境下仍可运行。
  - `getStats(Stats* out)`：返回连接数、失败次数等统计（用于 `/api/_debug/db` 等）。
- `MySqlDbPool`：
  - 持有 MySQL 连接配置（host/port/user/password/schema/timeout）；
  - 按需创建连接，并在 Repo 中以 RAII 方式使用。
- `NullDbPool`：
  - 所有方法返回“不可用”或空结果，但不会抛异常，用于 dev/PoC 环境。

### 3.2 Repo 模式

VA 使用 Repo 模式封装具体表的读写逻辑，典型例子：

- `SessionRepo`（`session_repo.hpp`）：
  - 负责向 `sessions` 表写入/更新订阅会话信息：
    - `append` 或 `upsert` 在订阅成功/失败/取消时记录 session；
    - 根据 stream/pipeline 查询历史会话。
- `EventRepo`（`event_repo.hpp`）：
  - 记录事件（节流、失败、状态流转等），支持按 pipeline/时间范围分页查询。
- `LogRepo`（`log_repo.hpp`）：
  - 将结构化日志（级别、pipeline、node、stream_id、message、extra JSON）落库，用于后续检索。
- `GraphRepo` / `SourceRepo`：
  - 读写 graph 与源相关信息，用于 CP 或管理工具回放与补全。

Repos 的共同特征：

- 构造时接收 `std::shared_ptr<DbPool>` 与 DB 配置；
- 提供最小 CRUD 与分页接口；
- 内部使用 prepared statement，避免 SQL 注入与重复拼接逻辑。

### 3.3 VA REST 与 DB 的交互

头文件：`video-analyzer/src/server/rest_impl.hpp`  
实现：`video-analyzer/src/server/rest_impl_core.cpp`、`rest_metrics.cpp` 等

- 在 `RestServer::Impl` 中：
  - 根据 `app_config().database` 调用 `DbPool::create`；
  - 若 `db_pool->valid()`：
    - 初始化 `LogRepo/EventRepo/SessionRepo/GraphRepo/SourceRepo`；
    - 启动后台写入线程 `startDbWorker`，每隔固定间隔批量 flush 事件与日志；
    - 启动 retention 线程，定期清理旧数据并记录 retention 指标。
- REST handler 与 Repo 的典型交互：
  - 订阅成功/失败：
    - 在订阅 LRO 完成时，将 session 结果（status/reason/pipeline_key/...）通过 `SessionRepo` 持久化；
  - 日志/事件：
    - 在关键路径打点处，将事件与日志追加到内存队列，由 `db_worker` 线程批量落库；
  - `/api/system/info` 与 `/api/_debug/db`：
    - 通过 `DbPool::getStats` 与 Repo 统计信息返回 DB 状态（驱动/host/schema/错误快照等）。

### 3.4 数据流时序（VA）

```mermaid
sequenceDiagram
  participant LRO as LRO Runner
  participant REST as VA REST
  participant DBW as DbWorker
  participant REPO as Session/Event/LogRepo
  participant DB as MySQL

  LRO-->>REST: 订阅完成 (success/failed/cancelled)
  REST->>REPO: 记录 session + event/log (入内存队列)
  loop 每隔 flush_interval
    DBW->>REPO: 批量取出 events/logs
    REPO->>DB: 执行批量 INSERT
    DB-->>REPO: ok/err
  end
```

## 4 Controlplane 存储访问设计

### 4.1 DB 模块与模式选择

头文件：`controlplane/include/controlplane/db.hpp`  
实现：`controlplane/src/server/db.cpp`

Controlplane 兼容多种访问模式：

- MySQL X DevAPI（`driver == "mysqlx"`）：
  - 使用 `mysqlx::Session` 与 X DevAPI 语句执行 JSON 查询；
  - 适用于直接返回 JSON 数组的场景（训练工件列表等）。
- ODBC MySQL（Windows）：
  - 使用 ODBC API 连接 MySQL 并执行 SQL 查询；
  - 主要用于读取 `models` 表，返回 JSON 序列。
- MySQL JDBC（可选）：
  - 仅在特定配置下使用，对 C++ 端来说是可选路径。

通过 `DbConfig` 中的 `driver/mysqlx_uri/host/port/user/password/schema/odbc_driver` 选择实际访问方式。

### 4.2 错误快照与调试

`db.cpp` 维护了一个进程内错误快照：

- `db_error_snapshot(nlohmann::json* out)`：
  - 返回最近一次 `mysqlx/odbc/jdbc` 相关错误，以 `{cat:{key:{...}}}` 形式存储；
- `db_error_clear()`：
  - 清空快照。

在 `controlplane/src/server/main.cpp` 中：

- `GET /api/_debug/db`：
  - 将错误快照与当前 DB 配置信息一起返回：`{code:"OK",data:{errors:{...},cfg:{...}}}`；
  - 便于快速确认连接字符串、driver 选择与最近错误。

### 4.3 训练相关数据流

Controlplane 的训练相关 API（`/api/train/*`）可以直接访问外部 Trainer 服务，也可以通过 DB 读取训练与工件信息：

- `train_create/train_update/train_get/train_list` 等辅助函数：
  - 在 `db.cpp` 中封装，使用 X DevAPI 或 ODBC 执行 SQL，然后返回 JSON 字符串；
  - 主线程在处理 `GET /api/train/status`、`/api/train/list` 等请求时调用这些函数，将结果透传给前端。

## 5 非功能性设计

### 5.1 性能与可靠性

- VA 侧通过批量写（events/logs）的方式减少 DB 写操作的频率，并在失败时进行节流日志输出；
- Controlplane 侧执行读多写少的查询，尤其是训练和模型列表，不在热路径上施加高压。

### 5.2 降级与回退

- 若 DB 配置为空或连接失败：
  - VA 使用 NullDbPool，所有落库操作静默失败但不影响订阅与推理链路；
  - CP 的训练相关 API 可能返回 `TRAINER_UNAVAILABLE` 或简化结果；`/api/_debug/db` 会显示具体错误信息。

### 5.3 安全

- 生产环境应为应用创建最小权限账号，仅授予 `cv_cp` 数据库所需的 CRUD 与索引权限；
- 不建议在配置文件中硬编码密码，可通过环境变量或安全配置管理工具注入。

本说明书作为存储访问层的详细设计基线，任何涉及新表、新 Repo 或更改 DB 访问方式的改动，均应同步更新本文件与 `数据库设计.md`，并视情况补充迁移脚本与回滚策略。
