# 路线图总览

- M0「打通链路与首屏」
  - 目标：分析页能稳定完成 WHEP 握手并亮屏。
  - 验收：/whep POST 201（含 Location）；setRemoteDescription 成功；receiver inbound-rtp bytes/pkts 连续增长，视频进入 playing。
- M1「兼容与稳态」
  - 目标：覆盖主流浏览器与常见编码配置，15 分钟稳定播放无抖动。
  - 验收：丢包<1%、重连<2 次/15min、无“Track is not open”告警；fmtp 对齐（pmode=1、lasym=1）且 Profile 与 NVENC 输出一致。
- M2「可观测与自动化」
  - 目标：端到端可观测、回归自动化与文档完善。
  - 验收：/api/system/info 暴露 whep_base；E2E 自动脚本通过；文档与排障手册齐备。

# 分阶段计划（表格）
| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| 后端握手修复 | createSession 正确返回 Answer | setRemote→addTrack(sendonly, mid)→createAnswer；localSdp 立即返回+回调兜底 | 状态竞态 → 原子化标志位；延时兜底 | POST /whep 201，answer_len>500 |
| 前端播放器健壮 | 可播放、断线重连、trickle 正确 | ontrack MediaStream 兜底；'a='+cand；mid='0'；end-of-candidates | 浏览器差异 → H.264 优先与日志细化 | setRemote ok；inbound-rtp 连续增长 |
| 编码/SDP 对齐 | 浏览器接受解码 | fmtp 仅 pmode=1/lasym=1；按 Answer PT 发送；清理多余 H264 PT | profile 不匹配 → 必要时对齐 profile-level-id | fps≥24、无周期抖动 |
| 线程/发送稳定 | 首帧快速稳定亮屏 | 等首个 IDR；SPS/PPS 预送；B-like 丢弃；RTP TS 单调 | IDR 稀疏 → 缩短 GOP/IDR 周期 | 首帧<2s；无“Track not open”异常 |
| 端到端验证 | 实机 E2E 与失败证据 | DevTools 抓 /whep 与 stats；最小页回归 | 端口不一致 → 校验 VITE_API_BASE/VA_REST_PORT | 15min 稳定播放 |
| 文档与自动化 | CONTEXT/ROADMAP/排障 | SOP、日志点位、E2E 脚本 | 依赖波动 → 固化版本与脚本 | 脚本 100% 通过 |

# 依赖矩阵
- 内部依赖：
  - 后端：`media/whep_session.*`、`transport_webrtc_datachannel.*`、`server/rest.cpp`。
  - 前端：`src/widgets/WhepPlayer/*`、`src/stores/analysis.ts`、`src/api/*`。
- 外部依赖（库/服务/硬件）：
  - `libdatachannel`、FFmpeg/NVENC/NVDEC、Vite/浏览器（Chrome）、RTSP 源（`rtsp://127.0.0.1:8554/camera_01`）、GPU（NVIDIA）。

# 风险清单（Top-5）
- 端口/环境不一致 → VA 未在 8082 启动 → 前端 /api 全红 → 启动 VA 并对齐 `VITE_API_BASE` 与 `VA_REST_PORT`。
- fmtp/profile 不匹配 → inbound-rtp 增长但黑屏 → 控制台打印 codecs 与 answer_head → 必要时按 NVENC SPS 写入 `profile-level-id`。
- ICE 候选异常 → NAT/网卡路径失败 → PATCH 无效、ICE failed → 先用 host-only、本机同网测试；必要时配置 STUN/TURN。
- IDR 稀疏/首屏慢 → 首个 IDR 迟到 → 等 IDR 与预送 SPS/PPS；缩短 GOP/IDR 周期。
- 线程竞态 → 回调与送帧线程可见性 → 原子化标志位与节流日志 → 若仍抖动，增加状态机与锁粒度。

