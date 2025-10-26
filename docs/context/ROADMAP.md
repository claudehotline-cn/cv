# 路线图总览

- M0「最小可用」：统一构建与对外面
  - 目标：controlplane 成为对外唯一 REST/SSE 网关；完成 /api/subscriptions（POST/GET/DELETE）、/api/system.info；清理构建与 gRPC 依赖；规范错误/指标。
  - 验收：CP 构建与冒烟通过；订阅 202+Location/ETag/304/DELETE 幂等；system.info 200 且含 VA/VSM 摘要；存在 cp_request_total 指标。
- M1「源管理与 Restream」：端到端源治理
  - 目标：/api/sources（列表/监控/SSE）、:enable|disable；订阅支持 source_id→restream URL 转换。
  - 验收：sources 列表 200；enable/disable 202；通过 source_id 创建订阅并可查询状态。
- M2「SSE 与安全」：稳定性与治理
  - 目标：VA Watch→SSE 桥接；CORS 白名单、Token/mTLS（可配置）；限流/熔断；Grafana 告警与指标完善。
  - 验收：SSE 长连稳定（>30min 无泄漏），关键路由具限流/熔断策略；告警规则生效。

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| M0 | /api/subscriptions、/api/system.info、构建统一 | vcpkg 工具链、gRPC deadline、ETag/304、错误映射 | 依赖混用 → 固定 vcpkg+屏蔽 Anaconda | 订阅 202/304 正确率>99%，/system.info P95<200ms |
| M0 | 指标与日志 | cp_request_total、分级日志、最小探针 | 噪声/缺口 → 白名单路由 + 采样 | 指标覆盖>80% 关键路由 |
| M1 | /api/sources（列表/监控/SSE）、:enable|disable | WatchState 首帧；SSE 回退；VSM Update | SSE 抖动 → 退避与心跳；缓存 | 列表 P95<300ms，SSE 3s 内首事件 |
| M1 | Restream 支持 | source_id→rtsp_base 拼装与校验 | 源异常 → 快失败+重试窗口 | 失败率<2%，重试不放大 |
| M2 | SSE 桥接 VA Watch | gRPC 流→SSE；keepalive/终止；释放资源 | 连接泄漏 → 统一关闭路径 | 长连 30min 无泄漏、CPU 稳定 |
| M2 | 安全与治理 | CORS 白名单、Token/mTLS、限流/熔断 | 配置复杂 → 环境模板与开关 | 关键路由 429/503 告警有效 |

# 依赖矩阵

- 内部依赖：
  - VA AnalyzerControl gRPC（订阅/控制/状态/Watch）
  - VSM SourceControl gRPC（WatchState/GetHealth/Update/Attach/Detach）
  - web-front（仅接入 CP 的 REST/SSE）
- 外部依赖（库/服务/硬件）：
  - vcpkg：gRPC、Protobuf、OpenSSL、Zlib、RE2、c-ares
  - OS/硬件：Windows + MSVC；CUDA（可选，影响 VA 推理路径）
  - 服务：MySQL、Redis（测试/数据）；RTSP 源（如 rtsp://127.0.0.1:8554/camera_01）

# 风险清单（Top-5）

- 依赖混用 → vcpkg 与系统/Anaconda 路径冲突 → 构建日志出现混杂前缀 → 强制 CMAKE_TOOLCHAIN_FILE / CMAKE_IGNORE_PREFIX_PATH，清 cache 重配
- gRPC 不稳定 → 下游不可用/超时 → 错误率/超时升高、system.info 缺字段 → 统一 deadline+重试/backoff，best-effort 聚合
- SSE 连接泄漏 → 长连增长 → 句柄/内存上升 → 统一关闭路径、keepalive、连接/内存监控
- 错误语义不一致 → 前端行为异常 → 客户端重试风暴 → 规范 gRPC→HTTP 映射（400/404/409/502），统一响应体
- 安全与访问治理不足 → 跨域/未鉴权访问 → 异常访问日志、带宽突增 → CORS 白名单、Token/mTLS、限流/熔断与告警

# 安全基线

- 默认不启用，按需开启（见 `controlplane/config/app.yaml` 示例）。
- M2 验收：CORS 白名单可配置；Bearer Token 生效且/metrics 豁免；简易限流可开启；错误码映射达成（400/404/409/502）。
