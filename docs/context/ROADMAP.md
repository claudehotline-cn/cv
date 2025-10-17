# 后续工作路线图（基于 CONTEXT 与数据库设计）

本路线图基于 docs/context/CONTEXT.md 与 docs/design/数据库设计.md，聚焦数据库接入、观测能力与可运维性，分阶段推进并给出明确验收标准。

## 范围与目标

- 数据持久化：sessions/events/logs 首要，其次 sources/pipelines/graphs/models 的元数据补齐。
- 读写路径：写入异步小批、读取支持分页/过滤，watch 长轮询保持不变。
- 连接管理：提供最小 `DbPool`，逐步替换零散连接；后续增强池内健康与指标。
- REST 接口：/api/db/ping、/api/sessions、/api/events、/api/logs、/api/*/watch、/api/db/retention/purge。
- 前端：Sessions 观测页与自动刷新，增强筛选/分页/导出。
- 运维：保留策略（定时清理）、故障节流、基础指标（写入失败/批量大小/QPS）。

## 里程碑

### M1（1–2 周）

- 构建与依赖
  - CMake 开关 `VA_WITH_MYSQL=ON`；自动检测 `third_party/mysql-connector-c++-*` 并链接。
  - `video-analyzer/config/app.yaml: database` 可用（host/port/user/password/db/pool）。
- 连接池与仓储
  - 提供最小 `DbPool`（`acquire()` RAII、min/max 配置、`valid()/ping()`）。
  - `EventRepo/LogRepo`：PreparedStatement 写入；批量（128/批）+ 事务；失败 5s 节流。
  - 异步写入器：500ms 聚合刷新；溢出丢弃并计数。
- REST 读写
  - `GET /api/db/ping` 返回驱动与连通性。
  - 读取：`GET /api/logs`、`GET /api/events/recent` 支持 `pipeline/level/stream_id/node/from_ts/to_ts/limit`。
  - watch 接口维持现状（内存 rev 指纹）。
- 测试与验证
  - `mysqlsh`：`SELECT COUNT(*) FROM events, logs` 与最近 N 条抽样。
  - Python 脚本（`video-analyzer/test/scripts`）：写入后回读 >0 行；FPS/检测数可选断言。
  - 前端（Playwright MCP）：Sessions 列表可打开且自动刷新正常（基础验证）。

验收：Windows 与 Linux 至少一种环境打包运行；写库/读库路径稳定，错误有节流日志；基础 E2E 通过。

### M2（2–4 周）

- Sessions 全量：`SessionRepo start()/completeLatest()/listRecent()`；订阅成功 Running，结束 Stopped，失败 Failed（含 `error_msg`）。
- Sessions REST：`GET /api/sessions` 与 `GET /api/sessions/watch`（长轮询返回 `{ rev, items }`）。
- 前端增强：Sessions 支持分页、时间窗过滤、状态高亮、导出 CSV。
- 保留策略：`POST /api/db/retention/purge` 已有；新增基于配置的定时清理（默认关闭）。
- 连接池增强：阻塞式借还、健康检查、统计指标（Prometheus 预留）。

验收：会话生命周期贯通、页面可用性提升；保留任务可配置；连接池指标可导出或日志化。

## 实施顺序（建议）

1) 打通 `DbPool` 与 `EventRepo/LogRepo` 的写入与分页读取（M1）
2) 增加 `GET /api/db/ping` 与日志/事件读端点（M1）
3) 异步写入器与错误节流（M1）
4) Sessions 生命周期与读端点（M2）
5) 前端 Sessions 增强 + 导出（M2）
6) 保留策略定时任务（M2）
7) 连接池增强与指标（M2+）

## 首批工程待办（Sprint-0）

- 后端
  - `video-analyzer`: `DbPool` 最小实现与单测（可选 mock）。
  - `EventRepo/LogRepo`：批量插入与 `listRecentFiltered()`。
  - `REST`: `/api/db/ping`、`/api/logs`、`/api/events/recent`。
  - 异步写入器：500ms 批量、128/批、5s 失败节流。
- 脚本与测试
  - `tools/db/import_schema.ps1` 使用说明补全与示例参数。
  - `video-analyzer/test/scripts/check_db_rw.py`：写入→读取断言、无 RTSP/HTTP 错误。
  - `mysqlsh` 校验脚本模板与 README 摘要。
- 前端
  - 接入 `/api/sessions`（若后端已就绪）；基础表格与自动刷新校验用例。

## 依赖与配置

- MySQL 8.0（InnoDB/utf8mb4），`db/schema.sql` 已提供。
- 连接器：`third_party/mysql-connector-c++`（含 `mysqlcppconn*.dll`/`libssl/libcrypto`）。
- 配置：`video-analyzer/config/app.yaml: database`（`pool.min/max` 建议 1/8 起步）。

## 风险与缓解

- 批量写入延迟：以 500ms 为起点，按实际吞吐调参；溢出队列丢弃并记录计数。
- 跨平台依赖：优先封装 CMake 探测与 `find_package` 回退；提供 Windows 预编译包路径。
- 查询放大：读取端加上 `limit`，索引 `(pipeline, ts)` 与 `(ts)` 覆盖。

---

以上内容每次迭代完成后同步到 `docs/context/CONTEXT.md` 的“后续计划”章节，并在本路线图更新阶段状态。

