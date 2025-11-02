# 路线图总览

- 里程碑 M0（容器化贯通最小闭环）
  - 目标：VA/CP/VSM/Web 全容器可启动；模型卷与日志卷生效；订阅→SSE→WHEP 播放在纯内网可达。
  - 验收：POST 订阅返回 202；SSE 出现 ready；WHEP Answer 含 192.168.50.78；VA 日志出现帧数累计。
- 里程碑 M1（稳定性与可观测）
  - 目标：冷启动稳定（小模型预热/超时可配）；基础指标暴露；故障可定位。
  - 验收：订阅平均 T99 < 8s（小模型）；CP 超时可调；Prometheus 指标完整；错误有因果日志链路。
- 里程碑 M2（性能与GPU路径）
  - 目标：CUDA EP 与 NVDEC/NVENC 协同；多流并发；端到端 FPS 达标。
  - 验收：GPU 推理启用（cuDNN 就绪）；N 并发流稳定；端到端 FPS≥目标阈值。

# 分阶段计划（表格）
| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| P0 | 最小闭环打通 | 模型/日志卷；SSE watch；WHEP LAN 候选 | 订阅超时→小模型/调超时 | 订阅成功率≥95% |
| P1 | 稳定性增强 | RTSP 打开参数；重连策略；指标导出 | RTSP 抖动→重连退避 | 单流 T99<8s（小模型） |
| P2 | GPU 启用 | ORT CUDA EP + cuDNN；NVDEC/NVENC | CUDA 版本不匹配→镜像固化 | GPU 启动成功率≥95% |
| P3 | 并发与压测 | 多流并发/限流；资源隔离 | 资源争用→配额/隔离 | N 路并发稳定 |
| P4 | 前端体验 | 自动播放/错误提示；候选可视化 | 浏览器策略→静音内联 | 首帧时间≤目标 |

# 依赖矩阵
- 内部依赖：
  - VA↔CP gRPC/HTTP（mTLS，证书 SAN 一致）。
  - CP SSE watch（/api/subscriptions/{id}/events）。
  - 图/模型配置与卷（/models，/logs）。
- 外部依赖（库/服务/硬件）：
  - FFmpeg/NVDEC/NVENC，ONNX Runtime（可选 CUDA EP + cuDNN）。
  - libdatachannel、IXWebSocket（WHEP）。
  - MySQL（host.docker.internal:13306）。
  - Windows 防火墙（UDP 10000–10100）。

# 风险清单（Top-5）
- 订阅超时 → 大模型冷启动/CP 超时偏低 → SSE 无 ready/504 → 预热小模型或升超时，记录阶段事件。
- 内网候选错误 → 未重写为 192.168.50.78 → ICE 失败 → DevTools 检 SDP；校验 `webrtc.ice.public_ip` 与端口映射。
- RTSP 抖动/不可达 → host 映射或源不稳定 → 帧数停滞/解码错误 → 调低延迟参数，增加重连与告警。
- GPU EP 不生效 → cuDNN 版本不匹配 → ORT 回落 CPU → 固化匹配版 CUDA/cuDNN，镜像集成自测。
- 证书/SAN 不一致 → CP↔VA 握手失败 → API 报错 → 统一生成/校验 SAN；在 CI 进行握手检测。

