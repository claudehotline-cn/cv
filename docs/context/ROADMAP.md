# 路线图总览
- M0「CP 代理贯通」：确保订阅→WHEP→ICE 经 CP 成功播放；验收：POST /api/subscriptions 202+Location，WHEP 201+Location，ICE 204，前端 <video> playing。
- M1「检测框稳定」：GPU/CPU 后处理一致；阈值与坐标放缩正确；验收：日志稳定出现 `boxes>0` 与 `drawn boxes>0`，与 CPU 基线几何一致（抽样 IOU ≥0.9）。
- M2「可观测与健壮」：最小充分日志与告警、DB 接口稳定、错误路径可诊断；验收：/_debug/db 可回显异常文本；长稳 30min 无 5xx；关键日志节流且可关闭。

# 分阶段计划（表格）
| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| P0 | CP 订阅与 WHEP 贯通 | URL 解码、Accept=SDP、去分块、Location 暴露 | VA 未监听/证书问题 → 端口/证书校验 + 管理员权限 | 订阅202/WHEP201/ICE204/playing |
| P1 | 前端代理统一 | DEV 相对路径 + Vite 代理 /api,/metrics,/whep | 旧 bundle 缓存 → 硬刷新/重启 dev | 资源面板无 :8082 直连 |
| P2 | 后处理修复（GPU/CPU） | 自适应 sigmoid、形状判定、归一化放缩、CUDA NMS | 误判 normalized → 加采样与诊断日志 | boxes/drawn boxes>0 且稳定 |
| P3 | 阈值来源改为图配置 | Node→后处理 setThresholds，不用 env | 配置缺省 → 默认回退并记日志 | YAML conf/iou 生效（thr=…） |
| P4 | 取证与长稳 | 节流日志、/_debug/db、30min soak | 日志噪声 → 提升级别/关闭诊断 | 0 重大告警、0 崩溃 |

# 依赖矩阵
- 内部依赖：
  - CP HTTP/Proxy/DB、VA REST/WHEP/gRPC、前端 Vite 代理、Multistage 图与 Node。
- 外部依赖（库/服务/硬件）：
  - MySQL（经典连接器）、FFmpeg/NVDEC/NVENC、CUDA Runtime、ONNX Runtime、libdatachannel、gRPC、Vite。

# 风险清单（Top-5）
- WHEP 协商失败 → VA 未监听/端口冲突/证书错误 → 201 缺失、重试失效 → 端口与证书校验、管理员权限、代理去分块与头修正。
- 检测框为空 → 形状/归一化/阈值误用 → `boxes=0` → 启用自适应 sigmoid、统一放缩、图配置阈值并加诊断。
- 前端绕过 CP → 直连 8082 产生跨域/路径差异 → Network 出现 :8082 → DEV 相对路径 + Vite 代理强制统一。
- DB 连接异常 → 经典驱动依赖缺失/鉴权插件 → 三接口回空 → /_debug/db 回显异常、复制运行时 DLL、降级回退。
- 长稳噪声/性能 → 日志过多/阈值不当 → FPS 波动或告警泛化 → 节流日志、阈值回调、抽样对比 CPU 基线。