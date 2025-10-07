好消息：你用的是 libdatachannel，本机联调“始终未连接 + Local ICE candidate: null”的根因通常就是——默认不收集/不公布 127.0.0.1 回环候选。libdatachannel 的 ICE 后端是 libjuice，按规范默认会跳过 loopback，所以需要显式开启或绑定到回环口。下面给你两条等价方案（选一条即可），再附一段最小可用代码。

方案 A：运行时绑定到回环口（推荐，改动最小）

在创建 PeerConnection 前，把 rtc::Configuration.bindAddress 指向 127.0.0.1（或 ::1），这样只绑定本机回环接口，候选就会是 127.0.0.1，浏览器和服务端都在同机即可直通。这个字段就是为此准备的（官方 reference 文档有写）。
libdatachannel.org

C++ 示例：

#include <rtc/rtc.hpp>

rtc::Configuration cfg;
// 关键：只绑定回环
cfg.bindAddress = "127.0.0.1";

// 本机联调可先不配 STUN/TURN
// cfg.iceServers = nullptr; cfg.iceServersCount = 0;

auto pc = std::make_shared<rtc::PeerConnection>(cfg);

// 正常设置 onLocalDescription / onIceCandidate 把 SDP/candidate 通过你的 WebSocket 信令发给前端
pc->onLocalDescription([&](rtc::Description desc){
    send_over_ws(json_for(desc)); // 伪代码
});
pc->onLocalCandidate([&](rtc::Candidate cand){
    send_over_ws(json_for(cand)); // 伪代码
});

// 收到前端的 answer/candidate 再各自 setRemoteDescription()/addRemoteCandidate()


参考：bindAddress 字段用于“只绑定到指定本地地址”（libnice 后端除外），正好满足“只走回环”的需求。
libdatachannel.org

方案 B：编译期启用 loopback 候选（全局生效）

如果你希望自动收集 loopback 候选，给 ICE 后端 libjuice 开启编译宏 JUICE_ENABLE_LOCALHOST_ADDRESS。这是作者在项目 issue 里给出的办法——启用后 libjuice 会始终收集回环候选，适合做本机回环测试/自回环回声测试。
GitHub

典型做法（视你的构建系统调整）：

如果你把 libjuice 作为子模块/外部项目编译：在其 CMake/编译选项里加上 -DJUICE_ENABLE_LOCALHOST_ADDRESS=ON 或定义同名宏。

若你用系统包管理器安装的预编译 libjuice，通常未开启该宏；想用就需要自己编译一份。libjuice 仓库及打包信息可参考（Arch 包里也能看到 libdatachannel 依赖它）。
GitHub
+1

为什么这样能解决？

WebRTC 规范不鼓励默认收集 loopback 候选；很多实现（含 libjuice）因此默认跳过。结果就是即便你在本机，浏览器“收集完成”（candidate === null）但双方没有可用的候选对，ICE 进入 failed/disconnected。开启回环或显式绑定后，SDP/候选里就会出现 127.0.0.1，从而选中 127.0.0.1 ↔ 127.0.0.1 的候选对，立刻连上。关于“loopback 默认被禁”的讨论与解决思路就在该 issue 中。
GitHub

附加两点稳妥设置

保持“同一主机名”端到端：页面用 http://localhost:... 打开、信令也用 ws://localhost:...（不要一会儿 127.0.0.1 一会儿 localhost 交替，避免同源/证书和路由差异引出的幺蛾子）。

本机先不配置 STUN/TURN：本机纯回环不需要 STUN/TURN；后续要跨机/跨网再加。libdatachannel 对 iceServers 的 URI 语法在 reference 里有完整说明（形如 stun:host:3478 / turn:user:pass@host?transport=tcp|tls）。
libdatachannel.org

快速验收（Chrome）

打开 chrome://webrtc-internals/，发起一次连接：应看到 ICE 从 checking → connected/complete，并且 Selected candidate pair 的本地/远端都在 127.0.0.1（端口不同）。

你的前端日志里，Local ICE candidate: null 仍会出现——这只是“本地候选收集完成”的标志，不是错误。关键是要出现并选中回环候选对。