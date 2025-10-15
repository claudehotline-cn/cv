# 项目上下文（最新）

本文件汇总当前对话期间已落地的关键改动、验证结果与后续计划，便于团队对齐与持续推进。

## 概览
- 分支：`IOBinding`
- 主要方向：数据库落地与观测能力、会话管理（Sessions）、前端观测页、性能与可运维性（批量写入、连接复用/池化）。

## 后端改动
- 数据库访问
  - 接入 Oracle MySQL Connector/C++（JDBC），优先使用 `third_party/mysql-connector-c++-9.4.0-winx64`，自动检测 `include/mysql/jdbc.h` 与 `lib64/vs14/mysqlcppconn.lib`。
  - CMake 开关：`VA_WITH_MYSQL=ON`；自动定义 `HAVE_MYSQL_JDBC` 时启用 JDBC 路径。
- DbPool
  - 保留 `valid()/ping()` 接口；新增最小连接池（JDBC，后向兼容）：`acquire()` 返回带 RAII 的连接句柄；内部空闲池（min/max 来自 `app.yaml: database.pool`）。
  - 现阶段 Repo 仍可沿用“每线程复用 + 局部创建”，后续逐步切换统一调用 `DbPool::acquire()`。
- 存储层与写入
  - `EventRepo/LogRepo`：`append()` 支持批量插入（每批 128 条，多 VALUES）；新增 `listRecentFiltered()` 支持 `stream_id/node/from_ts/to_ts` 过滤。
  - `SessionRepo`：`start()/completeLatest()/listRecent()`；订阅成功写入 Running，会话结束写入 Stopped；订阅失败写入 Failed（携带 `error_msg`）。
  - 异步写入器（500ms 批量，溢出丢弃）：写入失败以 5s 节流报错日志；DB 读取失败在 REST 层以 5s 节流告警。
- REST 端点
  - 健康：`GET /api/db/ping`
  - 会话：`GET /api/sessions`，`GET /api/sessions/watch`（长轮询 `{ rev, items }`）
  - 日志/事件（读）：
    - `GET /api/logs?pipeline=&level=&stream_id=&node=&from_ts=&to_ts=&limit=`
    - `GET /api/events/recent?pipeline=&level=&stream_id=&node=&from_ts=&to_ts=&limit=`
    - 长轮询保持不变：`/api/logs/watch`、`/api/events/watch`
  - 数据保留（手动）：`POST /api/db/retention/purge { events_seconds, logs_seconds }`

## 前端改动（web-front）
- 新增 Sessions 页面：`/observability/sessions`
  - 列表字段：`id/stream_id/pipeline/status/started_at/stopped_at/error_msg`
  - 过滤：`stream_id/pipeline`
  - 实时刷新：对接 `GET /api/sessions/watch` 长轮询
- API 封装（dataProvider）：`listSessions()`、`watchSessions()`
- 导航入口：Observability → Sessions

## 构建与运行
- 后端（Windows 示例）
  - 构建：`tools/build_with_vcvars.cmd`
  - 运行：`video-analyzer/build-ninja/bin/VideoAnalyzer.exe D:\Projects\ai\cv\video-analyzer\config`
  - 依赖 DLL：`mysqlcppconn-10-vs14.dll`、`libcrypto-3-x64.dll`、`libssl-3-x64.dll`（已复制到 `bin/`）
- 前端
  - 运行：`cd web-front && npm ci && npm run dev`（默认代理 `/api` 到 `http://127.0.0.1:8082`）

## 种子数据（已写入）
- graphs：`analyzer_multistage_example|_kpt|_roi_cls`（file_path 指向仓库相对路径）
- models：`det:yolo:v12l/v12x/v8n`，`seg:yolo:v12s_seg/v8s_seg`
- sources：`cam_01`（rtsp://127.0.0.1:8554/camera_01）及历史测试源（如 `cam_03/cam_fail/...`）
- 验证脚本：`mysqlsh` 已用于连通性与数据回读校验

## API 使用示例
- Sessions
  - `GET /api/sessions?stream_id=cam_01&pipeline=det_720p&limit=50`
  - `GET /api/sessions/watch?stream_id=cam_01&pipeline=det_720p&timeout_ms=12000&interval_ms=300`
- Logs/Events（过滤+时间窗口）
  - `GET /api/logs?pipeline=det_720p&stream_id=cam_01&from_ts=<ms>&to_ts=<ms>&limit=100`
  - `GET /api/events/recent?pipeline=det_720p&level=info&from_ts=<ms>&limit=50`
- 保留策略（手动清理）
  - `POST /api/db/retention/purge { "events_seconds": 86400, "logs_seconds": 86400 }`

## 验证记录
- mysqlsh：连通与数据查询（`SELECT COUNT(*) FROM events/logs/sessions;`、最近 N 条抽样）
- REST 自测：订阅/取消触发 DB 落库；`/api/sessions`/`/api/events`/`/api/logs` 回读正常
- 前端（Playwright MCP）：
  - 打开 `#/observability/sessions`，会话列表显示与自动刷新正常

## 后续计划
- P1 继续：
  - 将 `EventRepo/LogRepo` 统一切换为通过 `DbPool::acquire()` 获取连接；完成后做一次全量回归
  - Sessions 页增强：分页、时间窗过滤、高亮 Running/Failed；表格导出
  - 保留策略：支持配置化的定时清理（定期触发 purge；默认关闭）
- P2 展望：
  - 更完善的连接池（借助队列/条件变量，实现阻塞式等待、池内健康检查、统计指标）
  - 端到端观测指标：写库 QPS、失败计数、队列长度、purge 用时（Prometheus）

---
以上内容覆盖至本文件，后续迭代完成后将持续在此同步最新上下文。

