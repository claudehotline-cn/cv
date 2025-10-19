# 项目上下文（WHEP 播放修复与联调）

本次对话聚焦“前端分析页无法通过 WHEP 正常播放视频”，完成后端与前端多项修复，并用 DevTools 复测定位环境阻塞点。

## 仓库与目标
- 结构：`video-analyzer`（后端，含 WHEP）、`web-front`（前端）、`video-source-manager`、`docs/*` 等。
- 目标：让分析页通过 WHEP 稳定拉取 NVENC H.264 视频，支持 trickle ICE、断线重连与可观测日志。

## 关键问题与修复
1) WHEP 握手顺序错误导致 409
   - 现象：`createSession no local SDP`、`Unexpected local description`。
   - 修复：setRemote(Offer) → addTrack(sendonly, 用 Offer 的 a=mid) → createAnswer()，并直接 `generateSdp()` 返回；等待 `onLocalDescription`（2.5s），超时兜底读取 localDescription。

2) 前端 trickle 片段拼接错误
   - 现象：`a=candidate:candidate:...` 被拒。
   - 修复：改为 `'a=' + cand`；默认 `mid='0'` 对齐服务端；发送 end-of-candidates。

3) 前端绑定流与诊断不足
   - 修复：`ontrack` 兜底 `new MediaStream([ev.track])`；使用 `receiver.getStats()` 聚焦 inbound-rtp/track；打印选中 codecs；保持 H.264 优先。

4) SDP/编解码对齐
   - 修复：Answer SDP 仅确保 `packetization-mode=1`、`level-asymmetry-allowed=1`，不强制 `profile-level-id`；若多条 H.264 rtpmap/fmtp，仅保留选中 PT；按 Answer PT 重新配置 payloadType。

5) 媒体发送稳定性
   - 修复：送帧前等待首个 IDR，并在首 IDR 前发送缓存的 SPS/PPS；丢弃 B-like（非参考）帧；RTP TS 单调递增；可选 pacing；AVCC→AnnexB 归一化。

6) 线程可见性
   - 修复：`pcConnected/trackOpen/started/closed` 改为 `std::atomic<bool>`；回调线程 `.store()`，送帧线程 `.load()`，避免偶发“不显示”。

7) PATCH 解析鲁棒性
   - 修复：去除 CR 结尾，候选与 mid 按行解析；默认 `mid='0'`。

## DevTools 现网验证结果
- 前端（5173）可达，但所有 8082 API 请求（system/info、sources、subscribe 等）均 `net::ERR_CONNECTION_REFUSED`。
- 结论：后端 REST 未在 8082 监听，导致前端无法拉取 sources/订阅 pipeline，自然不会发起 `/whep`，因此“无视频”。

## 构建与运行
- 构建：`tools/build_with_vcvars.cmd`（Windows, MSVC+ninja）。
- 运行：后端 `VideoAnalyzer.exe <config>`，确保 `VA_REST_PORT=8082`；前端 `npm run dev`；可用 `public/whep_minimal.html` 做最小自测。

## 待办与验证
- 启动后端 REST 于 8082，前端再次联调：应出现 `/whep` 201 + Location、`setRemoteDescription ok`，inbound-rtp/track 指标递增，`video playing`。
- 若 inbound-rtp 增长但黑屏，核对 Answer 的 H.264 fmtp 与 NVENC 实际 SPS（必要时对齐 `profile-level-id`）。

## 风险要点
- 端口/环境不一致；fmtp/profile 不匹配；候选 NAT/网络限制；首个 IDR 过慢；线程竞态。已给出对应监控与预案。

