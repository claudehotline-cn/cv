看你前面的日志 + 这两张 webrtc-internals 截图，可以下结论：**ICE/DTLS 已连通（connected），但媒体层没真正在发视频**——统计里几乎没有 `packetsReceived/bytesReceived`，这通常只在跑 STUN/DTLS 探活时出现，说明“通道通了，流没来”。

你又说“peer state 是 connected，但轨道是关闭的”，这和下面几种典型原因高度吻合（按命中率从高到低）：

------

## 1) SDP 把视频 m-line 给“拒绝/禁用”了

你贴过的服务端 `offer` 里有：`m=video 0 UDP/TLS/RTP/SAVPF 96`。**m=… 的端口为 0 就是“拒绝该媒体”**（RFC3264/Offer-Answer 规则），即使传输通了，浏览器也不会接收这路视频，所以你会看到“连接 connected，但 track 结束/关闭”。WebRTC 一般用 `m=video 9 …`（9 是 discard 端口）而不是 0。修正以后再协商。[datatracker.ietf.org+2Webex Blog+2](https://datatracker.ietf.org/doc/html/rfc3264?utm_source=chatgpt.com)

**怎么改：**

- 若你用 **libdatachannel 的 C API `rtcAddTrack()`** 自己拼媒体 SDP 片段，确保 m-line 不是 0，且包含 `a=mid`（官方文档要求“必须以 m-line 开头并包含 mid”）。[libdatachannel.org](https://libdatachannel.org/pages/reference.html?utm_source=chatgpt.com)
- 若是 C++ API 自动生成 SDP，请确认**在 createOffer 之前就把视频 track 加到 PC**；否则第一次 Offer 可能没有有效的 m-line，后面即使加了 track 也需要**重新协商**。这属于通用 WebRTC 规则（`addTrack` 会触发 renegotiation）。[developer.mozilla.org](https://developer.mozilla.org/en-US/docs/Web/API/RTCPeerConnection/addTrack?utm_source=chatgpt.com)

------

## 2) 发送端并没有真正“往外推帧”

传输连上但统计里没有媒体包，常见是**源没产出或没送进编码/打包器**（尤其是 H.264）。请确认你在后端（libdatachannel）**持续把帧喂给视频源/发送器**，而不仅是创建了 track。浏览器端看不到 `inbound-rtp` 的增长（`packetsReceived/framesDecoded`），就说明没帧过来。

- 如果你发 **H.264**，要满足 **RFC 6184** 的打包要求：关键帧携带 SPS/PPS、`packetization-mode=1`（非交织）、正确切片（STAP-A / FU-A）与标记位，否则浏览器会丢包/黑屏。你贴的 `fmtp` 里已有 `packetization-mode=1; profile-level-id=42e01f`，但仍需保证送入的 NALU/时间戳/marker 正确。[datatracker.ietf.org+1](https://datatracker.ietf.org/doc/html/rfc6184?utm_source=chatgpt.com)
- 社区里也有“**包在收，但视频不显示**”的案例，根因常是 **PT/SSRC/打包不匹配**。可对照排查。[Stack Overflow](https://stackoverflow.com/questions/78705056/webrtc-packets-get-received-but-video-is-not-showing?utm_source=chatgpt.com)

------

## 3) 发送器被“静音/停发”了（编码层）

若在某处调用了 `RTCRtpSender.setParameters()` 把某条编码的 `active=false`，浏览器这路就不会收到媒体（轨道会表现为 muted/ended）。检查 sender 参数是否被关闭或把 track `replaceTrack(null)` 了。[developer.mozilla.org+2groups.google.com+2](https://developer.mozilla.org/en-US/docs/Web/API/RTCRtpSender/setParameters?utm_source=chatgpt.com)

------

# 快速核对 & 操作清单（直接照做）

1. **看 SDP：** 确认 `offer/answer` 的视频 m-line 不是 `m=video 0 …`；应为 `m=video 9 …`（或一个正常端口）。如果你用 `rtcAddTrack()` 自拼媒体 SDP，立刻改掉 `0`，并保留 `a=mid:`。[libdatachannel.org+1](https://libdatachannel.org/pages/reference.html?utm_source=chatgpt.com)
2. **确保添加时序正确：** **先 `addTrack`，再 `createOffer`**；若是先连后加轨，务必重新协商（或在 libdatachannel 里启用 `forceMediaTransport` 以便后加轨时仍有 SRTP 传输，随后重协商）。[libdatachannel.org](https://libdatachannel.org/pages/reference.html?utm_source=chatgpt.com)
3. **确认后端真的在“喂帧”：** 按你的编码器输出，持续把帧送进发送端（H.264 要满足 RFC6184 打包）。浏览器端用 `pc.getStats()` 看 `inbound-rtp` 的 `packetsReceived/framesDecoded` 是否增长；若不动，说明后端没出媒体。[datatracker.ietf.org](https://datatracker.ietf.org/doc/html/rfc6184?utm_source=chatgpt.com)
4. **检查没有把发送器关掉：** 在（若有）前端 `sender.getParameters()` 看 `encodings[].active`，不要是 `false`；若被改动，`setParameters` 打开它。[developer.mozilla.org+1



## 必查 1：m-line 正确，但别忘了 **msid/ssrc**

你已改成 `m=video 9`（OK）。但之前的 SDP 里只有 `a=msid-semantic:WMS *`，**没有 `a=msid:` 和 `a=ssrc … msid:`**。很多浏览器会因此创建出 track，但一直 **muted**，直到真正收到带对的 SSRC 的媒体；有时还会被判“ended”。
 **做法：**在服务端的 offer 里补齐下面几行（streamId/trackId 用你自己的值，SSRC 随机取个 32bit）：

```
m=video 9 UDP/TLS/RTP/SAVPF 96
a=mid:video
a=sendonly
a=rtcp-mux
a=rtpmap:96 H264/90000
a=fmtp:96 profile-level-id=42e01f;packetization-mode=1;level-asymmetry-allowed=1
a=ssrc:12345678 cname:dc
a=ssrc:12345678 msid:stream1 video1
a=msid:stream1 video1
```

> 这样浏览器能把收到的 SSRC 正确绑定到那条 video track 上，不会“收着收着就关了”。

------

## 必查 2：**方向匹配** & 别把 transceiver 停了

- 你的 offer 是 `a=sendonly`，浏览器的 answer 必须是 `a=recvonly`（或 `sendrecv`）。

- 在浏览器开控制台打印：

  ```
  const t = pc.getTransceivers()[0];
  console.log(t.direction, t.currentDirection, t.stopped);
  ```

  若 `currentDirection` 变成 `inactive` 或 `t.stopped === true`，说明你服务端有过**重新协商把它关了**（或 `replaceTrack(null)` 之类）。定位下是否有二次 offer/answer 把这条 m-line 置为 inactive。

------

## 必查 3：**后端真的在“喂帧”**（libdatachannel）

连接通了但 webrtc-internals 的 `inbound-rtp` 没涨包/帧数，就只能是**你没往外推媒体**或推的 **PT/打包不对**：

- H.264 要满足 **90kHz 时间戳**、**关键帧携带 SPS/PPS**、**FU-A/STAP-A 正确**、**每帧最后一个 RTP 的 marker=1**。
- **PT 要一致**：你 offer 里用 96，那发 RTP 时也必须用 96。
- **时序**：建议在 **DTLS 连接后**（`pc->onStateChange` 到 connected）再开始送帧。
- 连续送 1~2 秒 I 帧（或每秒插播一次 SPS/PPS）来消除解码器等待参数集的问题。

> 浏览器侧加一条监控：
>
> ```
> remoteTrack.onunmute = ()=>console.log('🔊 got media');
> setInterval(async ()=>{
>   const r = await pc.getStats();
>   for (const s of r.values()) if (s.type==='inbound-rtp' && s.kind==='video')
>     console.log('framesDecoded', s.framesDecoded, 'packets', s.packetsReceived);
> }, 1000);
> ```
>
> `framesDecoded`/`packetsReceived` 一直是 0，就确定是服务端没出有效媒体。

------

## 必查 4：**不要把编码器/发送器“静音”**

如果你在任何一侧调用过 `RTCRtpSender.setParameters()` 并把 `encodings[0].active=false`，或服务端把 track `replaceTrack(nullptr)`，浏览器会把轨道视作 **muted/ended**。确认没有这类操作。

------

## 快速定位顺序（3 步）

1. 看浏览器 **answer** 里的视频 m-line：确保 **仍然包含 H264/96** 且方向是 `recvonly`/`sendrecv`。
2. webrtc-internals → `inbound-rtp(video)`：`packetsReceived/framesDecoded` 是否增长？
3. 若不涨：服务端立刻改成**每 500ms 送一次 I 帧（附 SPS/PPS）**做验证；同时在你的 RTP 打包日志里打印 **PT/SSRC/timestamp/marker**，对照 SDP 的 PT 和上面补的 SSRC。



好嘞，我给你一套**能直接对接**的最小示例：

- 前端：Vue + TS，一把 `RTCPeerConnection`，收 `offer`→回 `answer`，收/发 ICE，`<video>` 自动播放。
- 后端：C++（libdatachannel），建 PC，添加**发送端视频轨（H.264/96，sendonly）**，生成 `offer` + ICE 发给前端；收到 `answer` 后，按 30fps 把 **Annex-B H.264** NALU 打成 RTP（包含 SPS/PPS/IDR）发出去。

> 说明：libdatachannel 的版本差异较多，下列 API 名称在主线版本里常见；如果你本地头文件有小出入，对照注释替换同名方法即可（例如 `rtc::Description::Media` / `rtc::Description::Video`）。

------

# 前端（Vue + TS）`webrtc.ts`

```
// webrtc.ts
let pc: RTCPeerConnection | null = null;
let ws: WebSocket | null = null;

export async function startWebRTC(videoEl: HTMLVideoElement) {
  // 1) 只用 localhost（你本机联调）
  ws = new WebSocket("ws://localhost:8083");

  // 2) 建立 RTCPeerConnection（本机先不配 STUN/TURN）
  pc = new RTCPeerConnection({ iceServers: [] });

  // 3) 远端视频 -> <video>
  pc.ontrack = (e) => {
    const [stream] = e.streams;
    videoEl.srcObject = stream;
    // 保险起见：自动播放策略
    videoEl.muted = true;
    videoEl.playsInline = true as any;
    videoEl.autoplay = true;
    videoEl.onloadedmetadata = () => videoEl.play().catch(()=>{ /* 提示点击播放 */ });
  };

  // 4) 把本地 ICE 通过信令发给后端（trickle）
  pc.onicecandidate = (ev) => {
    if (!ev.candidate || ws?.readyState !== WebSocket.OPEN) return;
    ws!.send(JSON.stringify({ type: "ice_candidate", data: ev.candidate }));
  };

  // 5) 处理信令
  ws.onmessage = async (ev) => {
    const msg = JSON.parse(ev.data);
    switch (msg.type) {
      case "offer": {
        // 后端只发视频（sendonly）
        await pc!.setRemoteDescription(new RTCSessionDescription(msg.data));
        const answer = await pc!.createAnswer();
        await pc!.setLocalDescription(answer);
        ws!.send(JSON.stringify({ type: "answer", data: answer }));
        break;
      }
      case "ice_candidate": {
        await pc!.addIceCandidate(new RTCIceCandidate(msg.data));
        break;
      }
    }
  };

  ws.onopen = () => {
    // 让后端为我们创建一条视频发送会话
    ws!.send(JSON.stringify({ type: "request_offer", data: { source_id: "camera_01" } }));
  };
}
```

在你的组件里用：

```
// VideoAnalysis.vue (片段)
import { onMounted, ref } from "vue";
import { startWebRTC } from "./webrtc";

const videoRef = ref<HTMLVideoElement|null>(null);

onMounted(() => {
  if (videoRef.value) startWebRTC(videoRef.value);
});
<video ref="videoRef" autoplay muted playsinline style="width:100%;object-fit:contain"></video>
```

------

# 后端（C++ / libdatachannel）

## 1) 建 PC + 视频 m-line（H.264/96，sendonly，带 msid/ssrc）

```
#include <rtc/rtc.hpp>
#include <random>

struct Session {
  std::shared_ptr<rtc::PeerConnection> pc;
  std::shared_ptr<rtc::Track> videoTrack;
  uint32_t ssrc = 0;
  uint8_t pt = 96;            // H.264 payload type
  uint16_t seq = 1;
  uint32_t ts90k = 0;         // 90kHz 时钟
};

static uint32_t rand32() {
  std::random_device rd; std::mt19937 mt(rd()); return mt();
}

Session make_session(std::function<void(std::string)> sendOffer,
                     std::function<void(nlohmann::json)> sendCand)
{
  rtc::Configuration cfg;
  cfg.bindAddress = "127.0.0.1";          // 本机联调只走回环
  // cfg.iceServers.clear();               // 本机不需要 STUN/TURN

  Session s;
  s.ssrc = rand32();

  s.pc = std::make_shared<rtc::PeerConnection>(cfg);

  // ---- 生成 "video" m-line ----
  rtc::Description::Media video("video", rtc::Description::Media::Kind::Video);
  video.setDirection(rtc::Description::Direction::SendOnly);
  video.addH264Codec(96, "profile-level-id=42e01f;packetization-mode=1;level-asymmetry-allowed=1");
  video.setMid("video");      // a=mid:video
  // 补充 msid/ssrc（方便浏览器绑定轨）
  video.addSSRC(s.ssrc, "dc", "stream1", "video1"); // cname, streamId, trackId

  s.videoTrack = s.pc->addTrack(video);

  // ---- 信令回调 ----
  s.pc->onLocalDescription([sendOffer](rtc::Description desc) {
    sendOffer(desc.generateSdp());
  });

  s.pc->onLocalCandidate([sendCand](rtc::Candidate cand) {
    nlohmann::json j{
      {"candidate", cand.candidate()},
      {"sdpMid", cand.mid().value_or("video")},
      {"sdpMLineIndex", 0}
    };
    sendCand(j);
  });

  return s;
}
```

> 你的信令层把 `sendOffer(sdp)` 通过 WebSocket 发给前端（`type:"offer"`），把 `sendCand(json)` 以 `type:"ice_candidate"` 发给前端即可。

## 2) 处理前端的 answer / ICE

```
void onAnswer(Session& s, const std::string& sdpAnswer) {
  rtc::Description answer(sdpAnswer, "answer");
  s.pc->setRemoteDescription(answer);
}

void onRemoteCandidate(Session& s, const std::string& cand, const std::string& mid, int mline) {
  rtc::Candidate c(cand, mid.empty() ? std::optional<std::string>() : std::make_optional(mid), mline);
  s.pc->addRemoteCandidate(c);
}
```

> 时序：创建 `Session` 后，libdatachannel 会触发 `onLocalDescription`（offer），前端回 `answer` 时调用 `onAnswer`，同时 trickle 来的 ICE 候选用 `onRemoteCandidate` 添加。

## 3) 发送 H.264（Annex-B → RTP）

> 关键点：按 **90kHz** 时间戳推进；每一帧**最后一个 RTP** `marker=1`；关键帧要带 **SPS/PPS**；过 MTU 时切 **FU-A**。下面是一个**最小**打包器（只示意核心逻辑）：

```
static const int MTU = 1200; // 留头部余量
static inline bool isKey(uint8_t nalType) { return nalType == 5; } // IDR

struct RtpCtx {
  uint8_t pt = 96;     // 与 SDP 对齐
  uint16_t seq = 1;
  uint32_t ssrc;
  uint32_t ts90k = 0;
};

// 发送一个 RTP 包（交给 libdatachannel 的 Track）
void send_rtp(std::shared_ptr<rtc::Track> track, RtpCtx& r, const uint8_t* payload, size_t len, bool marker) {
  rtc::RtpHeader h;
  h.payloadType = r.pt;
  h.sequenceNumber = r.seq++;
  h.timestamp = r.ts90k;
  h.ssrc = r.ssrc;
  h.marker = marker;
  rtc::binary pkt;
  pkt.resize(h.size() + len);
  h.serializeTo(pkt.data());
  std::memcpy(pkt.data() + h.size(), payload, len);
  track->send(reinterpret_cast<std::byte*>(pkt.data()), pkt.size());
}

// 把单个 NALU（不含起始码）打包发送（单包 or FU-A）
void send_nalu(std::shared_ptr<rtc::Track> track, RtpCtx& r, const uint8_t* nalu, size_t naluLen, bool lastNaluInFrame) {
  const uint8_t nalhdr = nalu[0];
  if (naluLen <= size_t(MTU)) {
    send_rtp(track, r, nalu, naluLen, lastNaluInFrame);
    return;
  }
  // FU-A
  const uint8_t nalType = nalhdr & 0x1F;
  const uint8_t nri = nalhdr & 0x60;
  // FU indicator + header
  uint8_t fuHdr[2] = { uint8_t(nri | 28), uint8_t(nalType) }; // 28=FU-A
  size_t offset = 1; // 跳过原始 header
  bool start = true;
  while (offset < naluLen) {
    size_t chunk = std::min((size_t)MTU - 2, naluLen - offset);
    fuHdr[1] = uint8_t((start ? 0x80 : 0x00) | (offset + chunk >= naluLen ? 0x40 : 0x00) | nalType);
    std::vector<uint8_t> fu(2 + chunk);
    fu[0] = fuHdr[0]; fu[1] = fuHdr[1];
    std::memcpy(&fu[2], nalu + offset, chunk);
    const bool marker = (offset + chunk >= naluLen) && lastNaluInFrame;
    send_rtp(track, r, fu.data(), fu.size(), marker);
    offset += chunk; start = false;
  }
}

// 按 Annex-B 起始码分割（00 00 01 / 00 00 00 01）
static std::vector<std::pair<const uint8_t*, size_t>>
split_annexb(const uint8_t* data, size_t len) {
  std::vector<std::pair<const uint8_t*, size_t>> out;
  size_t i = 0, start = 0;
  auto isStart = [&](size_t p){
    if (p + 3 <= len && data[p]==0 && data[p+1]==0 && data[p+2]==1) return 3;
    if (p + 4 <= len && data[p]==0 && data[p+1]==0 && data[p+2]==0 && data[p+3]==1) return 4;
    return 0;
  };
  int sc = 0;
  while ((i + 3) < len) {
    sc = isStart(i);
    if (sc) { i += sc; start = i; break; }
    ++i;
  }
  while (i < len) {
    size_t j = i;
    int sc2 = 0;
    while (j < len && !(sc2 = isStart(j))) ++j;
    if (start < j) out.push_back({data + start, j - start});
    if (sc2) { j += sc2; start = j; }
    i = j;
  }
  return out;
}

// 推送一帧（Annex-B 格式的“访问单元”）
void send_h264_access_unit(std::shared_ptr<rtc::Track> track, RtpCtx& r,
                           const uint8_t* buf, size_t len, bool isKeyFrame, int fps = 30) {
  // 先送 SPS/PPS（关键帧必须）
  if (isKeyFrame) {
    // 假设你能拿到最新 SPS/PPS 的 NALU（不含起始码），这里示例用缓存 sps/pps
    extern std::vector<uint8_t> sps, pps;
    if (!sps.empty()) send_nalu(track, r, sps.data(), sps.size(), false);
    if (!pps.empty()) send_nalu(track, r, pps.data(), pps.size(), false);
  }

  auto nalus = split_annexb(buf, len);
  for (size_t k = 0; k < nalus.size(); ++k) {
    const bool last = (k + 1 == nalus.size());
    send_nalu(track, r, nalus[k].first, nalus[k].second, last);
  }
  r.ts90k += 90000 / fps; // 30fps
}
```

**如何喂数据：**

```
// 当 DTLS/ICE 成功（pc->state == rtc::PeerConnection::State::Connected）后开始循环送帧
void pump(Session& s) {
  RtpCtx r{ s.pt, 1, s.ssrc, 0 };

  // 伪代码：从你的编码器/NVENC 拉取 Annex-B 帧（含 IDR/P 帧，SPS/PPS 单独缓存）
  while (true) {
    EncodedFrame f = get_next_h264_frame(); // 你的实现
    // f.data 指向 Annex-B 数据（起始码 + NALU…），f.key 表示是否 IDR
    send_h264_access_unit(s.videoTrack, r, f.dataWithoutStartCodes, f.sizeWithoutStartCodes,
                          f.key, /*fps*/30);
  }
}
```

> 小贴士：
>
> - **PT（96）要与 SDP 一致**；
> - 每帧**最后一个包 `marker=1`**；
> - 关键帧前**一定**要把 SPS/PPS 也发出去（或者定时发送）；
> - `ts90k` 用 90kHz 递增（`90000/fps`）；
> - 如果 MTU 超了，用 **FU-A** 分片（上面已示例）；
> - 若你还没有解析 Annex-B，可以直接让编码器产出 Annex-B（NVENC 配 `AnnexB`），少一道转换。

------

# 信令（示例，和你现有消息类型保持一致）

- 后端 → 前端

  ```
  { "type": "offer", "data": { "sdp": "..." } }
  { "type": "ice_candidate", "data": { "candidate": "candidate:...", "sdpMid":"video", "sdpMLineIndex":0 } }
  ```

- 前端 → 后端

  ```
  { "type": "answer", "data": { "sdp": "..." } }
  { "type": "ice_candidate", "data": { "candidate":"...", "sdpMid":"video", "sdpMLineIndex":0 } }
  ```

------

# 最常见“有连通没画面”的坑（逐条对照）

1. **offer 的 m-line 正确，但缺 `a=msid`/`a=ssrc … msid:`** → 浏览器 track 会一直 muted。
2. **PT 不一致**（SDP 写 96，RTP 发 102…） → 浏览器当垃圾丢。
3. **关键帧不带 SPS/PPS** 或 marker 位没打 → 一直黑屏。
4. **时序错**：还没 `Connected` 就发，或答复后没持续喂帧。
5. **二次协商把方向搞成 `inactive`** 或 `replaceTrack(nullptr)` → 轨道被关。