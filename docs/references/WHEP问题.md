1. 好的，我已经把你给的项目包解开通读了关键代码（后端 `video-analyzer/src/media/*`，以及前端 `web-front/src/widgets/WhepPlayer/WhepPlayer.vue`）。结论很明确：**前端拿不到视频，不是因为 ICE/DTLS 或前端逻辑，而是后端 Answer SDP 的“轨道/编解码协商细节”有瑕疵，导致发送轨一直没有 open，后端不停打印 `waiting track open`，前端自然就一直 `no inbound-rtp`**。下面把“为什么”和“怎么改”一次讲透。

   ------

   ## 你现在代码里发生了什么（定位到文件/逻辑）

   ### 1) 后端的 WHEP 会话创建（`whep_session.cpp`）

   - 你**正确**地在生成 Answer 之前就：
     - 从浏览器 Offer 里解析了 H264 的 **动态 PT**（`offer_h264_pt`）；
     - 创建发送视频轨：`rtc::Description::Video vdesc("video"); vdesc.setDirection(SendOnly); vdesc.addH264Codec(sess->payloadType, …);`
     - 绑定 SSRC/流：`vdesc.addSSRC(ssrc, "va", "stream1", "video1");`
     - `pc->setRemoteDescription(offer)` → `pc->setLocalDescription(Answer)`。

   > 这部分顺序是对的：**先 addTrack，再 setLocalDescription**。

   - 你把发送端打包器 `H264RtpPacketizer` 的 **payloadType** 也设成了 `sess->payloadType`（就是 Offer 里的那个 PT）。这也对。
   - 生成 Answer 后，你会做一个 `sdp_check` 日志，检查：
     - `dir=sendonly`（方向对）
     - `h264_pt=…`（从 Answer 文本里扫到的第一个 H264 的 pt）
     - `msid` 是否出现（`a=msid:` 或 `a=ssrc:… msid:`）
     - 并打印 `used_pt=<sess->payloadType>`（你打算用的 PT）

   **关键问题出在这两项：**

   ### 2) Answer 里“第一个 H264 的 PT”不一定是 Offer 的 PT

   - 你的日志里我们看到过：**`used_pt=103`**（从 Offer 解析），但是 `sdp_check` 扫到的 **`h264_pt=121`**。
   - 这意味着 **Answer 里其实出现了两个 H264 条目**（例如 121 和 103），而**排在前面的那个不是 103**。
   - WebRTC 的真正“已协商 PT”由底层栈决定；一旦底层选用的 PT 与你发送端包头里的 PT 不一致（你按 103 发，但底层谈成 121），**发送轨不会 open**，于是你这里每一帧都会 hit 到 `videoTrack->isOpen()==false` → 继续打印 `waiting track open`。

   > 你当前的 `inject_h264_fmtp` 只是在 Answer 文本里给“**第一个** H264 rtpmap”补了 `fmtp`，这反而会**加重“第一个不是 103”的影响**。

   ### 3) Answer 里缺“轨道绑定”（`msid=0`）

   - 多次日志显示 `msid=0`。
   - 你虽然调用了 `vdesc.addSSRC(ssrc, "va", "stream1", "video1")`，按理应生成 `a=ssrc:... msid: stream1 video1`，但从实际 Answer 看**没出现**（lib 的行为/版本差异，或被后续处理覆盖）。
   - **没有 `a=msid`（或 `a=ssrc … msid …`）** 时，浏览器端经常不会创建可接收轨（也不会发 RTCP RR），而 libdatachannel 侧的 sender 也**不会进入 open**，就形成了你看到的“死等待”。

   ------

   ## 直接可落地的修复（按优先级执行）

   ### ✅ 修复 1：确保 Answer 中只保留“一个 H264 条目”，其 **PT 必须等于 Offer 的 PT**

   **做法 A（首选，纯 API 方式）**
    在构造 `vdesc` 时只保留你想要的 H264，并确保它排第一；不要让库再塞入别的 H264：

   ```
   rtc::Description::Video vdesc("video");
   vdesc.setDirection(rtc::Description::Direction::SendOnly);
   
   // 如果 API 支持，先清空默认 codec；没有就忽略这行
   // vdesc.clearCodecs();
   
   const uint8_t offerPt = sess->payloadType; // 例如 103（你已从 Offer 解析）
   // 只添加这一条 H264（packetization-mode=1 很关键）
   vdesc.addH264Codec(offerPt, rtc::DEFAULT_H264_VIDEO_PROFILE);
   
   // 强烈建议：显式添加 RTCP FB
   vdesc.addRtcpFeedback(offerPt, "nack");
   vdesc.addRtcpFeedback(offerPt, "pli");
   vdesc.addRtcpFeedback(offerPt, "transport-cc");
   
   // 绑定 SSRC & msid（见修复 2）
   vdesc.addSSRC(sess->ssrc, "va", "stream1", "video1");
   
   sess->videoTrack = pc->addTrack(vdesc);
   ```

   **做法 B（兜底，文本“瘦身”）**
    如果库仍然在 Answer 里塞了多个 H264，你可以在 `localSdp` 拿到后、返回给前端之前，对 **m=video 段**“瘦身”：

   - 只保留 `a=rtpmap:<offerPt> H264/90000` 与其对应的 `a=fmtp:<offerPt> ...`、`a=rtcp-fb:<offerPt> ...`；
   - 删除其它 H264 PT 的行；
   - `m=video` 行的 PT 列表也只留下 `<offerPt>`（以及必要的 rtx 映射，如你启用的话）。

   > 这样能 100% 保证底层协商到的就是 `<offerPt>`，与你的打包器 `payloadType` 一致，发送轨就会 open。

   ### ✅ 修复 2：保证 Answer 里有 **`a=msid`（或 `a=ssrc … msid …`）**

   - 你已经调用了 `addSSRC(ssrc, "va", "stream1", "video1")`，但从实际看没落到 SDP。建议**再保险**地在 Answer 文本阶段做一次检查/注入：

     - 若没有 `a=msid:` 行，则在该 m=video 段内插入：

       ```
       a=msid: stream1 v0
       ```

     - 或者确保出现 `a=ssrc:<ssrc> msid: stream1 v0`（保持你生成时的 `streamId/trackId` 一致即可）。

   > 这一步能“强迫”浏览器创建接收轨，配合修复 1，**服务端 sender 会立刻 open**，你的 `waiting track open` 会消失。

   ### ✅ 修复 3：**不要改写 Offer 的 `m=video` 端口**

   - 你前端日志里多次出现 `m=video 7174/7607` 这样的端口；标准做法是 **9**（占位），真正连通靠 ICE。
   - 不要手改端口；按你现在的前端代码（`WhepPlayer.vue`）来看，已经是原生 `createOffer`，应该不会去改。

   ### ✅ 修复 4：Trickle PATCH 的格式要严格（你前端已改对）

   - 之前你把 `a=candidate …  a=mid:0` 放一行，后端解析不到 `a=mid`。

   - 你现在前端已经按 **CRLF 分两行**发：

     ```
     a=candidate:...
     a=mid:0
     ```

     后端 `patchSession` 用 `std::getline` 解析就 OK 了。额外建议把解析出来的 `mid` 做个 `trim()`，防止出现 `mid='0\n'` 这种日志。

   ------

   ## 我在代码里看到的可改进处（方便你直改）

   - **`whep_session.cpp` → `attachMediaHandlers(Session&)`**
      这里把 `RtpPacketizationConfig` 的 `payloadType` 设成了 `sess->payloadType`（来自 Offer），这点保持不变。但“协商侧”要保证 Answer 只保留该 PT 的 H264（见修复 1）。

   - **`whep_session.cpp` → 生成 Answer 后的 `inject_h264_fmtp(...)`**
      你是“找到**第一个** H264 rtpmap，然后替换/插入 fmtp”。

     - 如果 Answer 里头一个 H264 不是 Offer 的 PT，这段处理会错位。
     - **建议**：改成**先精确定位 `<offerPt>` 的 rtpmap**，对它对应的 fmtp 做处理。若找不到 `<offerPt>`，就说明 Answer 被库改坏了，直接“瘦身”到只留 `<offerPt>`。

   - **`sdp_check`**
      你已经把 `dir/h264_pt/msid` 打印出来，这非常有用。修完后，期望日志应该是：

     ```
     dir=sendonly h264_pt=<和 offer 相同> msid=1
     ```

     一旦这样，后面的 `track open sid=...` 会出现，前端的 `inbound-rtp` 会马上有数据。

   ------

   ## 前端当前实现（`WhepPlayer.vue`）是OK的

   - 你已经把 **H264 优先** 做了（`setCodecPreferences`），
   - `ontrack` 里正确把 `srcObject` 绑定到 `<video>`，
   - Trickle PATCH 分行，
   - 统计里打印 `inbound-rtp`。
      **所以真正的阻断点还是后端“轨没 open”。**

   ------

   ## 预期现象（修复后）

   - 后端日志新增：`[WHEP] track open sid=...`，`first IDR observed` 之后不再打印 `waiting track open`；
   - 前端 1～2 秒内出：
     - `ontrack`、`track onunmute`、`video playing`，
     - `getStats` 看到 `inbound-rtp(kind=video)`，`bytesReceived` 持续增长；
     - 不再刷屏 `no inbound-rtp/track yet`。

   ------

   ## 若你想最快验证

   1. 在返回给前端之前，把 **完整 Answer 的 m=video 段**打印出来（只需这一段）。
      - 检查：是否只有一个 H264；其 PT 是否等于 Offer 的；是否有 `a=msid` 或 `a=ssrc … msid …`。
   2. 如果不是，先“文本瘦身 + 注入 msid”试一版；你会立刻看到轨 open/视频起来。
   3. 再回头把“只添加一个 H264（Offer PT）”固化到 `vdesc` 的构造逻辑里，去掉瘦身的兜底。