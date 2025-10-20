看你的日志，WHEP 整条链路其实是通的：SDP 协商正常、ICE connected、服务端持续在送帧（frames=... bytes=... 一直增长），但是前端表现为“只在关键帧刷新，其它时间都卡着”。这类现象99% 是“帧边界/打包”问题——浏览器端 H.264 depacketizer 只有在识别到“这一帧结束”的条件（RTP 同一时间戳的一组包的最后一个包 marker(M)=1）时才会把这帧交给解码器；如果你送的不是完整的一帧（access unit），或是分片/分组方式不对，浏览器就会一直攒包，直到下一次遇到能独立解码的 IDR 关键帧才更新画面，于是看起来就像“只播关键帧”。

对比你给的两个测试文件和工程里（零拷贝分支）的实现，有几个关键差异/易错点：

1) 你的测试程序“先把数据整理成完整一帧的 Annex-B”，再交给 libdatachannel 的 H264 打包器

在 whep_standalone_server.cpp 里，服务端用的是 libdatachannel 自带的 H264RtpPacketizer，并明确以 StartSequence（起始码 00 00 00 01） 作为 NALU 分隔方式，然后把一整帧（Annex-B 字节流）交给 sendFrame：

先创建打包器并挂到 track 上：H264RtpPacketizer(... NalUnit::Separator::StartSequence, ..., 1200)，vtrack->setMediaHandler(h264pack)。

如果源是 MP4（AVCC/length-prefixed），先用 h264_mp4toannexb 或 avcc_to_annexb 转成 Annex-B。

每次 把整帧 Annex-B 放进一个 rtc::binary frame，同一个 RTP 时间戳（90k 时钟）送出，然后再把 ts += step。

这样做的效果：libdatachannel 会自动把这“一帧里的所有 NALU”做 FU-A/STAP-A 切片与聚合，并且只在这一帧最后一个 RTP 包上置 M=1。浏览器就能准确知道“这一帧结束了”，于是连续解码、连续渲染。

2) 你工程（零拷贝分支）里很可能没有保证“按整帧送入 + 分隔方式与字节流类型匹配”

从你给的运行日志能看到工程侧也在建 H264RtpPacketizer 并打印了 pt=103 maxFrag=1200，说明走的也是相同思路；但前端只在 IDR 更新，强烈暗示下面至少踩中了一个坑：

Annex-B vs AVCC 搭配错误
H264RtpPacketizer 构造时选择了 NalUnit::Separator::StartSequence（期望字节流带 00 00 00 01 起始码）。如果你零拷贝路径里从编码器/解码器拿到的是 AVCC（length-prefixed） 数据，却原样喂给了这个打包器，它会把“长度字段”当作 NAL 头来切分，结果整帧被错误拆分，M 位也就对不上；浏览器端就会把绝大多数“非关键帧”当成不完整帧丢弃或等待。你的测试程序之所以正常，正是因为它在送入前显式做了 AVCC→Annex-B（或直接就是 Annex-B）。

按 NALU（甚至按切片）而不是按帧送
如果零拷贝路径里你对每个 NVENC 输出片段（有时是切片）各自调用一次 sendFrame，打包器会把“每个切片”都当成一帧处理并立刻 M=1，浏览器端看到的就是“很多没有组成完整画面的‘帧’”，只在遇到能独立解码的 IDR 才更新。这点在测试程序中是通过“合为一帧再送”避免的（见 sendFrame(..., FrameInfo(ts90)) 的用法）。

RTP 时间戳/marker 与帧边界不一致
只要不是“同一真实帧的所有 RTP 包共用同一个时间戳，且最后一包 M=1”，浏览器就会把该帧当不完整处理。测试程序里是“固定步长 ts += step，一帧一次”，工程里如果把同一帧拆成多次 sendFrame（每次时间戳都递增），也会复现“只有关键帧动”。

3)（次要但要确认）SDP 的 profile/packetization-mode 要与码流一致

你工程日志里看见用的是 pt=103，对应 packetization-mode=1; profile-level-id=42001f（Baseline）。如果 NVENC 输出的是 Main/High（常见）而你又强行用 Baseline 的 PT，多数浏览器依然能解，但有过“只在关键帧更新、P 帧大量掉”的兼容性坑；最稳妥的做法是从对端 Offer 里挑选一个与实际 SPS 里的 profile-level-id 匹配的 H264 PT，你的测试程序就是直接 addH264Codec(s->pt, DEFAULT_H264_VIDEO_PROFILE) 后由对端选择，但它的码流与 fmtp 是对得上的。

建议你在工程里立刻做的三个定位/修正点

确保送入打包器的是“完整一帧”的 Annex-B

如果当前拿到的是 AVCC（length-prefixed），要么像测试程序那样在送入前做一次 AVCC→Annex-B（同功能的 avcc_to_annexb 就几行），要么把 H264RtpPacketizer 的分隔方式换成 Length（如果你确认全路径都是 AVCC）。

伪代码（送帧处）：

// frameBuf = 一帧的 Annex-B 字节流（包含该帧的所有 NALU）
rtc::binary frame(frameBuf.size());
std::memcpy(frame.data(), frameBuf.data(), frameBuf.size());
rtc::FrameInfo finfo(ts90);
vtrack->sendFrame(std::move(frame), finfo);
ts90 += step;  // 只在“整帧”后递增时间戳


这和你的测试程序做法一致（它每次 send 的就是整帧）。

不要把同一帧拆成多次 sendFrame
如果编码器回调是“分片/切片回调”，请先在你这层按时间戳或帧序号聚合成一帧的所有 NALU，再调用一次 sendFrame。否则 marker 与 RTP 时间戳都会错位，浏览器端就只会在 IDR 时渲染。

让 SDP 与真实码流匹配
从浏览器 Offer 里挑选与你实际码流 profile 一致的 H264 PT（比如 High 就用 profile-level-id=64001f 的那个），或者把 NVENC 编码配置成 Baseline/Constrained Baseline（无 B 帧、CAVLC/或相容）与 103 一致。你的前端打印的 capabilities 里有多个 H264 PT，可选空间足够。你也可以在关键帧处“重复发送 SPS/PPS”（NVENC 有对应开关），提升兼容性。

最快验证法（不用抓包也行）

服务端打印： 在送帧前做一个 very-light 的 Annex-B 解析，打印这一“整帧”里首个 VCL 的 nal_type（1/5）和本次 FrameInfo.timestamp；确保“非关键帧”也每 33ms（或你的 fps）递增一次 timestamp，且“同一帧只 send 一次”。

浏览器端看 webrtc-internals： 观察 inbound-rtp 的 framesDecoded 是否只在关键帧时蹦一下；如果是，十有八九就是“帧被拆碎 / M 位没落在真正的帧末”。

小结（结论）

你的两个测试文件之所以“都能播”，核心在于它们把 H.264 整帧（Annex-B）一次性交给了 H264RtpPacketizer，而零拷贝分支很可能是喂了 AVCC 或者按 NALU/切片在“帧中间”就递增了时间戳/打了 M，导致浏览器只在 IDR 时才能“凑齐一帧”并刷新。
把输入类型与分隔方式对齐（Annex-B↔StartSequence / AVCC↔Length），并且一帧只调用一次 sendFrame，基本就能把“只播关键帧”的问题一次性解决。