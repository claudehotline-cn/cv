2025-10-25

任务：根据 controlplain 设计与计划，梳理后续工作、未实现项，以及 VA 中嵌入式控制面/REST 的迁移边界。

- 输入文档：
  - docs/design/controlplain_design.md
  - docs/plans/controlplain_plan.md

- 现状结论：
  - VA 已提供 AnalyzerControl gRPC（video-analyzer/src/control_plane_embedded/api/grpc_server.cpp）。
  - VSM 已提供 SourceControl gRPC（video-source-manager/src/app/rpc/grpc_server.cc）。
  - controlplane 独立项目当前不存在，需要新建并承担前端唯一服务面（REST+SSE），通过 gRPC 对接 VA/VSM。
  - VA 现有 REST（video-analyzer/src/server/*）覆盖大量能力，最终应迁移“对前端开放”的路由到 CP，VA 保留底层指标与内部管理端点。

- 待办/未实现（按文档 M0/M1/M2）：
  - M0（最小可用）：
    - 新建 controlplane 工程（CMake+vcpkg），HTTP 基础路由：/healthz、统一 CORS/OPTIONS。
    - gRPC 客户端封装：VA AnalyzerControl、VSM SourceControl。
    - 订阅 API：POST/GET/DELETE /api/subscriptions（202+Location、ETag/304 约定）。
    - /api/system/info 聚合（VA QueryRuntime + VSM 摘要，1–2s 缓存）。
  - M1（Restream & 源管理）：
    - /api/sources 列表与 watch；/api/sources:enable|disable → VSM Update。
    - restream 语义：POST subscriptions 支持 source_id → 组装 restream.rtsp_base+source_id。
  - M2（SSE 与安全）：
    - /api/subscriptions/:id/events SSE：桥接 VA Watch 流；/api/sources/watch_sse。
    - 安全：mTLS/Token、CORS 白名单、速率与熔断；Grafana 告警指标（cp_request_total 等）。

- 迁移建议（VA → CP）：
  - 必须迁移（前端面）：
    - /api/subscriptions*、/api/system/info、/api/sources*、/api/orch/*（编排/Attach/Detach/Health）。
  - 可迁移/可代理：
    - /api/models、/api/profiles、/api/pipelines（经 VA gRPC QueryRuntime）。
    - /api/graphs、/api/graph/set、/api/preflight（可映射至 Apply/SetEngine）。
    - /api/logs*、/api/events/*（如前端依赖，可由 CP 统一 SSE/拉流）。
  - 保留在 VA：
    - /api/metrics（Prometheus 明细指标）与底层调试/DB 维护（rest_db/rest_admin_wal 等）。
    - WHEP/媒体推流（rest_whep）：保持在 VA，CP 仅负责控制与编排。

- control_plane_embedded 目录处置：
  - 不删除：其实现的 AnalyzerControl gRPC 服务是 CP 的后端依赖，应长期保留（可后续重命名为 rpc/ 或 control/api/）。
  - 删除条件：仅当 VA 的 gRPC 服务迁出 VA 进程（不在当前路线）时才可能考虑移除。

- 里程碑化实现步骤（建议）：
  1) 搭建 controlplane 骨架 + CMake/vcpkg + HTTP/CORS；
  2) 接 VA/VSM gRPC（客户端）+ 配置（VA/ VSM 地址）+ 日志与指标；
  3) 实现 M0 API + 最小 ETag 语义；
  4) 实现 M1 源管理/Restream；
  5) 实现 M2 SSE & 安全；
  6) web-frontend 切换 baseURL 至 CP，灰度/回滚策略；
  7) 在 VA 侧按开关关闭 REST（或仅保留内部）并逐步下线对外路由。

