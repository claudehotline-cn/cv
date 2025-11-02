WBS 范围说明

- 目标：将 VA 对外 REST 职责上收至 CP；VA 仅保留媒体输出与自身指标。全链路在 TLS 下完成回归（正/负路径、SSE Soak、mTLS）。
- 不改动：构建目录与构建产物；媒体（WHEP/HLS）继续由 VA 提供。

  1. 方案与基线

- 1.1 架构决策与边界确认（REST/编排归属CP；WHEP/metrics留VA）
- 1.2 影响面清点与变更清单冻结
  - 参考：video-analyzer/src/server/*.cpp、controlplane/src/server/*.cpp
- 1.3 回滚策略定义（双栈开关、灰度→下线）

  2. VA 侧改造（裁剪 REST）

- 2.1 增加开关 VA_DISABLE_HTTP_PUBLIC（CMake 选项 + 宏）
  - 影响：CMakeLists.txt, video-analyzer/src/server/*.cpp
- 2.2 路由裁剪/置灰
  - 移出/禁用：rest_control.cpp、rest_subscriptions.cpp、rest_sources.cpp、rest_system.cpp、rest_db.cpp、rest_models.cpp、
        rest_routes.cpp
  - 保留：rest_whep.cpp、rest_metrics.cpp；可选保留 admin/logging 仅内网端口
- 2.3 编译与链接修复（移除依赖/头文件耦合）
- 2.4 兼容期 G410/404 置灰（可选，短期保留提示）

  3. CP 侧承接（REST 完整对外）

- 3.1 路由补齐与对齐
  - /api/system/info、/api/subscriptions/*、/api/sources/*、编排 REST（attach_apply/drain/delete/status/hotswap）
  - 文件：controlplane/src/server/main.cpp（或拆分路由文件）
- 3.2 通过 gRPC 调 VA/VSM（TLS）
  - 客户端：controlplane/src/server/grpc_clients.cpp
- 3.3 审计与指标
  - 审计补全：attach_apply 失败码等
  - 指标 method 维度：cp_backend_errors_total{service,method,code}

- 4.1 TLS 环境变量与证书路径校验（VA/VSM/CP）
- 4.2 一键脚本复用与校验
  - tools/start_stack_tls.ps1、tools/stop_stack.ps1
- 4.3 前端默认路由检查（指向 CP：18080）

  5. 测试与验证（TLS 基线）
      - 脚本：controlplane/test/scripts/smoke_orch_positive_flow.ps1

- 5.2 编排负路径稳定化并默认纳入
  - INVALID_ARGUMENT/NOT_FOUND/UNAVAILABLE/TIMEOUT 映射与审计断言
- 5.3 SSE Soak（TLS）
  - ≥10 分钟，资源/FD 泄漏监测；脚本：soak_cp_sse_watch.py
- 5.4 mTLS 回归
  - tools/test_mtls_connectivity.ps1、tools/test_mtls_negative.ps1

  6. CI/CD 与观测

- 6.1 CI 扩展覆盖（Windows）
  - TLS 最小冒烟 + 编排正/负 + mTLS 正/负；产物归档
- 6.2 Grafana/Prometheus 联动
  - 看板聚合固定为 sum by (service,method,code)；规则验证
- 6.3 日志与证据归档目录规范化

  7. 文档与开发体验

- 7.1 更新 README 与一键化文档（TLS 默认）
  - docs/README-TLS-一键化.md、web-front/README.md
- 7.2 更新上下文与路线图
  - docs/context/CONTEXT.md、docs/context/ROADMAP.md
- 7.3 变更日志与接口迁移指南

  8. 发布与回滚

- 8.1 灰度（CP 路由接管，VA Public HTTP 置灰）
- 8.2 验收窗（监控 24–48h）
- 8.3 全量下线 VA Public HTTP；保留 WHEP/metrics
- 8.4 回滚预案（关闭 VA_DISABLE_HTTP_PUBLIC + 切回前端直连 VA 的兜底配置）

  9. 风险与缓解（执行内置）

- 9.1 证书/路径不一致 → 启动失败/握手错误 → 脚本统一注入与预检查
- 9.2 Windows 文件锁/LNK1104 → 先停进程再构建
- 9.3 时序/重启导致超时 → 端到端重试与健康检查
- 9.4 指标口径不一致 → 固化聚合口径与回归脚本
- 9.5 长连资源泄漏 → Soak ≥10 分钟与阈值告警

  交付与完成定义

- 交付物：编译开关/改造补丁、CP 路由补齐、脚本与 CI、Grafana/告警、文档与迁移指南。
- 完成定义：TLS 下正/负编排与 mTLS 全绿、SSE Soak ≥10 分钟通过、前端仅连 CP 正常、VA Public HTTP 被禁用且媒体/metrics 可用、告警/面板可复现。
