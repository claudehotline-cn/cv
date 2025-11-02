总体里程碑

- M0 最小可用
  - 完成 gRPC 客户端封装（VA/VSM），实现 /api/subscriptions（POST/GET/DELETE）、/api/system/info，统一 CORS/错误语义与 ETag。
- M1 源管理与 Restream
  - 实现 /api/sources（列表/监控）、:enable|:disable；订阅支持 source_id→restream URL 转换。
- M2 SSE 与安全
  - VA Watch→SSE 桥接；安全治理（CORS 白名单、Token/mTLS）、限流/熔断；CP 指标完善与告警。

  详细任务分解

- 基础设施与配置
  - controlplane 工程骨架校验：CMake + vcpkg + 生成到 controlplane/build/bin。
  - 配置加载与探针：启动探测 VA/VSM 可用性，失败时降级/回退日志。
  - 标准化返回体与错误码映射（gRPC→HTTP）。
- gRPC 客户端封装与健壮性
  - 位置：controlplane/src/server/grpc_clients.cpp, include/controlplane/grpc_clients.hpp
  - 封装 API：
    - VA AnalyzerControl：Subscribe/Unsubscribe/SetEngine/QueryRuntime/Apply/Drain/Watch
    - VSM SourceControl：WatchState/GetHealth/Update/Attach/Detach
  - 加入超时、重试、backoff、错误类别映射（INVALID_ARGUMENT/NOT_FOUND/UNAVAILABLE→400/404/503）。
- M0 API：/api/subscriptions 与 /api/system/info
  - 位置：controlplane/src/server/main.cpp（handler 逻辑）、include/controlplane/store.hpp（cp_id 状态存储）
  - /api/subscriptions
    - POST：受理 202+Location；支持 stream_id|profile|source_uri|model_id，ETag 生成。
    - GET：返回 {id, phase, reason?, pipeline_key}，支持 If-None-Match→304。
    - DELETE：幂等；尝试 VA 取消。
  - /api/system/info
    - 聚合 VA QueryRuntime 与 VSM 简要健康度，2 秒缓存，错误降级。
- M1 API：/api/sources 与 Restream
  - 位置：controlplane/src/server/main.cpp, include/controlplane/events.hpp
  - 列表与监控（轮询占位→SSE 完成前回退）：
    - GET /api/sources：汇总 VSM WatchState 快照；统计 fps/phase/attach_id。
    - POST /api/sources:enable|disable：调用 VSM Update(options.enabled)。
  - Restream 语义：
    - /api/subscriptions POST 支持 source_id；按 config.restream_rtsp_base 组装 source_uri。
- M2：SSE 桥接与安全
  - VA Watch→SSE
    - 位置：include/controlplane/watch_adapter.hpp, src/server/watch_adapter.cpp, include/controlplane/sse_utils.hpp
    - 功能：拉取 VA Watch（gRPC 流），逐条写出 data: 事件；keepalive/终止、错误码映射。
  - 安全与治理
    - CORS 白名单与 OPTIONS 细化；将 Token/mTLS 配置预留（运行参数或环境变量），回滚为 plaintext。
    - 基于路由/方法的速率限制与熔断（简单计数→后续引入更完整方案）。
  - 指标与告警
    - 指标：cp_request_total{route,method,code}、cp_feature_enabled{feature}、下游错误计数。
    - 控制台/文件日志分级，关键操作留审计线索。
- 控制接口映射：/api/control/*
  - 位置：controlplane/src/server/main.cpp
  - REST→gRPC 代理：
    - /api/control/apply_pipeline, /apply_pipelines
    - /api/control/hotswap
    - /api/control/pipeline (DELETE)
    - /api/control/status
    - /api/control/drain
- Orchestration：/api/orch/*
  - 位置：controlplane/src/server/main.cpp
  - VA/VSM 组合编排：attach_apply/detach_remove/health，错误一致性与回滚语义。
- 观测与日志
  - 位置：controlplane/src/server/metrics.cpp, include/controlplane/metrics.hpp
  - 完善 Prometheus 输出；关键路由记录时延分布（后续直方图），Grafana 告警规则建议。
- 前端切换与灰度
  - 将前端 baseURL 指向 CP；灰度路由开关（CP→VA 直透备选），回滚预案：切回 VA REST。
- VA 侧收口与保留
  - 保留在 VA：
    - /metrics、/api/admin/wal/、/api/db/、媒体/WHEP（rest_whep）
  - 逐步关闭对外 REST（仅内部端口开放或开关控制）；保留 gRPC 与内部端点。

  从 VA 迁移到 CP 的路由清单（建议优先级）

- 高优先级
  - /api/subscriptions（POST/GET/DELETE）与 /api/subscriptions/:id/events（SSE）
  - /api/system/info
  - /api/sources（GET/watch，占位→SSE）与 :enable|:disable
  - /api/control/*（apply/apply_pipelines/hotswap/pipeline/status/drain）
  - /api/orch/*（attach_apply/detach_remove/health）
- 可选迁移/代理（视前端依赖）
  - /api/models、/api/profiles、/api/pipelines
  - /api/graphs、/api/graph/set、/api/preflight
  - /api/logs*、/api/events*、/api/sessions*

  测试与验收

- M0
  - 构建通过（VA/CP/VSM）；/api/system/info 200；/api/subscriptions POST→202，GET→200/304，DELETE 幂等。
- M1
  - /api/sources 200；enable/disable→202；restream 订阅链路（source_id→rtsp_base+id）可用。
- M2
  - /api/subscriptions/:id/events SSE 可跑通（若 VA Watch 可用）；CORS/安全策略可控；指标可被抓取。

  风险与回滚

- 风险
  - gRPC 版本/依赖不一致 → 已统一 vcpkg；构建脚本固定工具链。
  - SSE 桥接稳定性/资源清理 → 流式读取与连接管理需严格。
- 回滚策略
  - CP 挂载失败 → 前端直接回切 VA REST。
  - 逐路由灰度切换，保留 CP→VA 直通代理开关。
