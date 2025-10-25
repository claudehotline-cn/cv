# controlplain 推进计划（无桥接 + Restream）

## 里程碑
- M0 最小闭环（2–3 天）
  - 构建/CMake + gRPC 客户端；订阅 REST（POST/GET/DELETE）最小闭环；/api/system.info 聚合；CORS 与 cp_* 指标。
- M1 Restream 与源管理（3–5 天）
  - VSM 启动自拉上游并 Restream；CP 订阅支持 source_id→restream URL 转译；源启停（enable/disable）；面板/告警。
- M2 SSE 与安全（5–7 天）
  - VA Watch 对接 SSE；横向扩展与负载均衡；mTLS/Token；版本与回滚；E2E 文档。

## 实施步骤（按顺序）
1) 工程化与依赖
- `controlplain/CMakeLists.txt` 引入 `gRPC::grpc++`、`protobuf::libprotobuf` 与 proto 生成；`tools/build_controlplain_with_vcvars.cmd` 使用 vcpkg toolchain。
- HTTP 监听与基础路由 `/healthz`，统一 CORS/OPTIONS。

2) gRPC 客户端封装
- 实现 VA AnalyzerControl 与 VSM SourceControl 客户端（超时/重试/错误分类）。
- 前置：VA 提供 `Watch` 流式接口（若缺失，先落 REST 最小闭环与源管理，再接入）。

3) 订阅 REST（M0→M1）
- M0：POST/GET/DELETE 使用 CP 自主 `cp_id` 与内存 store；返回 202+Location、ETag/304；DELETE 幂等。
- M1：POST `/api/subscriptions` 支持 `source_id`；CP 以 `restream.rtsp_base + source_id` 转译为稳定端点调用 VA SubscribePipeline（不再触达 VSM）。

4) system.info 聚合（M0）
- 聚合 VA/VSM 结构化信息，1–2s 只读缓存；字段标注 `source=config|env|va|vsm`。

5) VSM 源管理（M1）
- GET `/api/sources`：优先 `WatchState` 首帧，失败回退 `GetHealth`。
- POST `/api/sources:enable|disable`：调用 VSM `Update(options.enabled)`；保留 attach/detach 过渡期。

6) 观测与告警（M1）
- 暴露 `cp_request_total{route,method,code}`、`cp_feature_enabled{feature}`；补 Grafana 面板与告警规则（Ready 比例、失败原因 TOP、退避窗口）。

7) SSE 与安全（M2）
- 对接 VA `Watch` 流式事件至 SSE；前端 JWT/OIDC（可选）；CP→VA/VSM mTLS/Token；回滚与降级脚本。

## 验收清单
- 最小 API：POST 202+Location、GET ETag/304、DELETE 202 全通过。
- Restream 订阅：仅凭 `source_id` 可订阅；/api/sources 列表与 enable/disable 生效；状态与指标可见。
- SSE：对接后事件稳定；整体无桥接、低耦合；可一键回滚。

