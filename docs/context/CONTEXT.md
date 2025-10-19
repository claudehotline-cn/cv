# 当前对话关键信息（WHEP 连贯性排障）

## 背景
- 现象：前端播放“很卡/几秒动一下/像只播关键帧”。将 GOP 调小后体感略好。
- 架构：VA(8082) 提供 WHEP；另有最小后端(8090) + 最小页可流畅播放。
- 推流样例：ffmpeg 从 mp4 以 CFR 基线、zerolatency、bf=0、keyint=60 推 RTSP。

## 取证结论
- DevTools 对 8082 的 analysis 页与最小页：
  - inbound-rtp 每 2 秒增加约 120 帧（fps≈60），video.currentTime 等速递增，渲染连续；非“只关键帧”统计特征。
- VA 日志：发送侧每秒 packets≈+30，持续输出；无节流；pc connected/track open 正常。

## 主要修复（8082 已生效）
1) AnnexB 检测与 AVCC 转换更健壮：
   - 先扫描 00 00 01/00 00 00 01；仅在非 AnnexB 时尝试 AVCC→AnnexB，失败不改原数据。
2) IDR 前注入 SPS/PPS：
   - 每逢 IDR，SPS/PPS 与 IDR 同一 timestamp 发送；首帧若缺 SPS/PPS 且为非 IDR，等待 IDR，避免裸 P 帧不可解。
3) 固定 RTP 时基与分片兼容：
   - 每帧 ts += 90000/30（等效 30fps）；
   - Answer SDP 强制 H264 `packetization-mode=1; level-asymmetry-allowed=1`。
4) 不丢帧与双 key 去重：
   - 不丢 B-like；fullKey+baseKey 同时路由并按 sid 去重。
5) 默认无节流：
   - pacing 关闭（VA_WHEP_PACE_BPS>0 才启用）。
6) 编码端（libx264）增强：
   - `repeat-headers=1`（每个 IDR 前带 SPS/PPS）。

## 前端配合
- WhepPlayer：默认关闭 flow guard 与高频 stats（仅 `VITE_WHEP_DEBUG=1` 时启用），避免主线程干扰。
- 最小页 whep_minimal.html 用于对照验证。

## 仍存在的体感问题
- 用户在“某具体页面/播放器路径”仍感觉像只播关键帧；analysis/最小页未复现。
- 高度可疑：该页面的会话/协商差异或渲染/布局阻断。

## 下一步定位计划
- 在“问题页面”用 DevTools 采 10–12 秒 inbound-rtp：`framesDecoded/framesPerSecond/framesDropped/jitter/bytes/packets`；与 analysis/最小页对比。
- 若 inbound 每秒≈30/60 仍体感卡：切换为极简 WhepPlayer（仅 ontrack+play）A/B 以排除页面干扰；若仍卡，导出应答 SDP 首段核对 fmtp/pt 与最小页一致性。
- 若 inbound 本身间歇：进一步核查 RTP 片段与 Marker（在 VA 侧临时加 seq/ts/M/FU.S/E 日志），或临时 GOP=15 验证 IDR 周期影响。

## 已提交与证据
- 关键代码：`video-analyzer/src/media/whep_session.cpp`（最小稳定策略）、AnnexB 修复；SDP fmtp 补丁；x264 repeat-headers。
- DevTools 截图：
  - `logs/devtools_analysis_continuity.png`
  - `logs/devtools_minimal_8082.png`
- 日志路径：`D:\Projects\ai\cv\logs\video-analyzer-release.log`

