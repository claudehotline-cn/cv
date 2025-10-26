# 路线图总览

- 里程碑 M0｜TLS/mTLS 与编排基线
  - 目标：TLS 一键启动；mTLS 正/负通过；编排正/负纳入冒烟并稳定；前端可经 CP 访问基础 API。
  - 验收：start_stack_tls 成功；test_mtls_* 通过；run_cp_smoke（非 Min）通过，归档日志齐备。
- 里程碑 M1｜观测与联调稳定
  - 目标：方法维度指标校验；Grafana/告警口径统一；SSE Soak 稳定（2–10 分钟）；前端分析页可发起订阅并看到起播。
  - 验收：metrics method 增量用例通过；面板/告警命中示例；Soak 无异常；分析页出现 /whep 201 并显示画面。
- 里程碑 M2｜端到端体验与 CI 完备
  - 目标：VA 公共 REST 完成收口（410 置灰可选）；CI 含 full（VA/VSM）流；文档与一键化完成；取证流程标准化。
  - 验收：VA 仅保留 /metrics 与 /whep；cp_full 成功并归档 logs/**；README/指南完整。

# 分阶段计划（表格）
| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| P0 | TLS/mTLS 可用 | VA/VSM TLS；CP TLS 客户端；一键脚本 | 证书缺失→启动前校验 | mTLS 正/负 100% 通过 |
| P1 | 编排正/负稳定 | attach→status→drain→delete | 启停时序→延迟重试 | 连续3轮无 5xx/UNAVAILABLE |
| P1.5 | 指标与告警 | method 维度；Grafana/规则 | 口径不一→统一 by(service,method,code) | 指标/告警可复现 |
| P2 | SSE Soak | 2–10 分钟稳定 | 抖动→keepalive/重连 | 无异常断流/FD 增长 |
| P3 | 前端分析起播 | 订阅→WHEP→播放 | 订阅 400→参数兜底 | 出现 /whep 201 且可见画面 |
| P4 | CI Full | 构建 VA/VSM+非 Min | 缺依赖→vcpkg 缓存 | CI 全绿，上传 logs/** |

# 依赖矩阵
- 内部依赖：
  - controlplane（REST/SSE/编排/指标/告警）
  - video-analyzer（gRPC 被控端 + WHEP + metrics）
  - video-source-manager（源控制 gRPC）
  - web-front（路由到 CP；WHEP 直连 VA）
- 外部依赖（库/服务/硬件）：
  - gRPC/Protobuf、OpenSSL、vcpkg、CMake/VC++、Node.js
  - RTSP 源：`rtsp://127.0.0.1:8554/camera_01`
  - GPU（可选，保留 CPU 回退）

# 风险清单（Top-5）
- 证书/路径不一致 → 启动握手失败 → /metrics 不通、gRPC UNAVAILABLE → 启动前校验 + 统一脚本注入
- 文件锁与链接失败 → 进程未停干净 → LNK1104 → 构建前 stop/kill 流程
- 订阅 400/超时 → 参数缺失/后端未 ready → /api/subscriptions 400、无 /whep → 前端兜底参数 + 先跑编排正向
- 指标口径不一致 → 面板/告警偏差 → method 缺失/聚合不当 → 固化 sum by (service,method,code) 并回归
- Soak 漏洞 → 长连/重连压力 → FD/内存缓升 → 2–10 分钟 Soak 与周期性重启演练
