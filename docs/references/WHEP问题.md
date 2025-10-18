稳了，这份**前端日志**把症状说得很清楚：

- WHEP 会话已创建（201）、ICE/PC 都 **connected**、`setRemoteDescription ok`；
- 但持续输出 **`stats: no inbound-rtp/track yet`**，说明**浏览器端没有收到任何入向 RTP**。
- 所以前端“卡住”等视频是**后端没真正开始发包**或**协商细节不匹配**导致的——和你前一份后端日志里的“track 未 open / sessions=0 或 waiting track open”完全对得上。

下面我把**从这份前端日志能定位到的问题**、**必修修复**、以及**前端侧增强自检**一次性给全。

------

## 这份前端日志暴露的关键信号

1. 会话/ICE 正常，但**没有入向 RTP**

```
[WHEP] POST /whep status=201
[WHEP] ice.state= connected
[WHEP] pc.state= connected
[WHEP] setRemoteDescription ok
[WHEP] stats: no inbound-rtp/track yet   （持续打印）
```

=> 不是网络/权限问题，是**媒体没发过来**（或协商后无法接收）。

1. 你的 **Offer m 行端口被写成了 7607**（非常不寻常）

```
offer_sdp_head ... m=video 7607 UDP/TLS/RTP/SAVPF ...
```

- 浏览器生成的 m 行端口**应该是 9**（占位）。
- 出现具体端口，多数是你在某处**改写了 SDP**。虽然一般不直接致命，但这是高危信号：说明你可能对 SDP 做了非必要的修改（和后端实现的“PT/方向/msid”等联动容易踩坑）。
   **建议：**不要改写 m 行端口；只通过 WHEP PATCH 上报 `a=candidate` 行即可。

1. 你的 PATCH 片段仍然把两条属性写在**同一行**

```
a=candidate:...  a=mid:0
```

- 正确应为**两行**：

  ```
  a=candidate:...
  a=mid:0
  ```

- 尽管这次 ICE 已连通，但这种格式对某些实现会造成解析扰动，建议立刻修。

1. 一堆扩展/iframe/i18n 报错是**噪音**

- `chrome-extension://invalid/`、`"[object Object]" is not valid JSON`、`codes.forEach is not a function` 这些和 WebRTC 媒体无关，但推荐顺手修掉，避免淹没真正的信令/媒体日志（下面附快速修法）。

------

## 必修修复（和后端配合，能一次性解决“无 inbound-rtp”）

> 结合你上一条后端日志，我强烈建议按这三条执行；这是最可能的一击即中：

1. **保持 H264 的 Payload Type 与浏览器 Offer 完全一致**

- 你后端日志出现过：`used_pt=96` 但随后“selected_pt=121 reconfigured”，这会让浏览器**不认这条 m=video**，从而**不产生 inbound-rtp**、服务端 track 也**一直不开**。

- **规范**：Answer 的 H264 动态 PT **必须沿用** Offer 中那条的 PT（通常是 `96`）。同时 Answer 里要有：

  ```
  a=rtpmap:96 H264/90000
  a=fmtp:96 packetization-mode=1;profile-level-id=42e01f;level-asymmetry-allowed=1
  ```

  以及 `a=sendonly`。

1. **先建 Sender/Transceiver（sendonly + H264/PT=96），再 CreateAnswer**

- 正确顺序：
   `setRemoteDescription(offer)` → **AddTransceiver/Track（direction=sendonly，锁定 H264/PT=96，设置 msid）** → `createAnswer` → `setLocalDescription(answer)`
- 反过来（先 createAnswer 再改配置）会导致 Answer 里**没有你的发送轨信息**，从而**track 永远不开**。

1. **Answer 的 m=video 段必须含 `a=sendonly` + `a=msid`（或 ssrc+msid）**

- 推荐 Unified Plan：

  ```
  a=msid: stream1 v0
  a=sendonly
  ```

- 缺少 msid 很多浏览器不会创建可见的接收轨，也不发 RTCP RR，仍旧“无 inbound-rtp”。

> 做完以上三点，**后端的 “waiting track open / Track is not open” 会消失**，前端立刻会看到 inbound-rtp。

------

## 前端侧：加 3 个“自证/限流”点（帮助你在前端快速判定是后端没发）

### 1) 限制编解码为 H264 优先（避免协商到非预期）

```
// 在 createOffer 之前：
const tr = pc.addTransceiver('video', { direction: 'recvonly' });
const caps = RTCRtpReceiver.getCapabilities('video')!;
const h264 = caps.codecs.filter(c => c.mimeType.toLowerCase() === 'video/h264');
tr.setCodecPreferences([...h264, ...caps.codecs.filter(c => c.mimeType.toLowerCase() !== 'video/h264')]);
```

### 2) 打印协商方向与 ontrack

```
pc.ontrack = (ev) => {
  console.log('[WHEP] ontrack kind=', ev.track.kind, ev.streams.map(s=>s.id));
  ev.track.onunmute = () => console.log('[WHEP] track unmuted');
};

setTimeout(() => {
  pc.getTransceivers().forEach((t,i)=>{
    console.log('[WHEP] tr', i, 'dir=', t.direction, 'current=', t.currentDirection);
  });
}, 0);
```

- 期望 `currentDirection`（前端视角）为 `recvonly`。如始终拿不到 `ontrack/onunmute`，十有八九是**后端 Answer 缺 msid 或 track 未 open**。

### 3) `getStats()` 验证是否真的“无 inbound-rtp”

```
const stats = await pc.getStats();
const inbound = [...stats.values()].filter(r => r.type === 'inbound-rtp' && r.kind === 'video');
const pairs = [...stats.values()].filter(r => r.type === 'candidate-pair' && r.nominated);
console.log('[WHEP] inbound', inbound, 'pair', pairs);
```

- 有 nominated 的 pair，但 **inbound 为空/bytesReceived 不变** ⇒ **后端没发**（就别纠结前端了）。

------

## 你这份日志里还能顺手修的“小毛病”

- **PATCH 片段换行**
   现在是：`a=candidate:...  a=mid:0`（同一行）
   改成：

  ```
  a=candidate:...
  a=mid:0
  ```

  以及在 gathering 完成时发送：

  ```
  a=end-of-candidates
  ```

- **video autoplay 避免被策略拦**（虽然现在根因不是这个，但建议写上）
   `<video playsinline muted autoplay>`，并在 `onunmute` 后再 `video.play()`。

- **i18n 报错（codes.forEach）**
   `codes` 可能是 string/object 而不是数组，封装一下：

  ```
  const toArray = (x:any)=> Array.isArray(x) ? x : (typeof x==='string' ? [x] : Object.values(x ?? {}));
  const codesArr = toArray(codes);
  codesArr.forEach(...);
  ```

- **iframe JSON.parse 报错**
   只在是字符串时再 `JSON.parse`：

  ```
  window.addEventListener('message', (e) => {
    const d = e.data;
    if (typeof d === 'string') {
      try { const obj = JSON.parse(d); /* ... */ } catch {}
    } else {
      // 已是对象，按对象处理
    }
  });
  ```

------

## 快速复盘检查清单（把问题一锤定音）

1. **Answer m=video**：包含 `a=sendonly`、H264 的 `rtpmap/fmtp`，**PT 等于 Offer 的 96**，并有 `a=msid`（或 ssrc+msid）。
2. **后端添加 sender 的时机**：在 `createAnswer/setLocalDescription` 之前就完成，并与上面 PT 一致。
3. **Track open 之后再发**：移除/减少 `waiting track open`，或清晰地在 `onOpen/connected` 时开始送帧。
4. **前端**：限制 H264、打 `ontrack/onunmute`、`getStats` 看 inbound。
5. **不改写 m 行端口**，PATCH 只发 `a=candidate`（换行正确）以及 `a=end-of-candidates`。