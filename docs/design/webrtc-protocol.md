# Video Analyzer WebRTC 通信协议

本文档描述当前 `video-analyzer` 后端内置的 WebRTC 信令及数据通道约定。服务端使用 libdatachannel 建立点对点连接，通过 DataChannel 发送经 JPEG 编码的分析帧。所有信令消息均通过 WebSocket（默认 `ws://<host>:8083`）交换，格式为 JSON。

## 总体流程

1. **WebSocket 连接**：客户端连接 `ws://host:8083`。
2. **认证**：客户端发送 `auth` 消息，服务端返回 `auth_success`。
3. **请求 Offer**：客户端发送 `request_offer`，指明想要观看的 `source_id`。
4. **创建 Offer**：服务端生成 SDP `offer`，并通过信令返回。
5. **Answer & ICE**：客户端发送 SDP `answer`，双方互换 `ice_candidate`。
6. **DataChannel 建立**：命名为 `video` 的数据通道打开后，服务端按帧推送 JPEG 数据。

REST 控制面（例如 `/api/subscribe`）负责创建/销毁管线；WebRTC 信令只负责媒体传输协商。

## 信令报文示例

### 认证

```json
{
  "type": "auth",
  "data": {
    "client_type": "web_client",
    "client_id": "web_1696400000"
  },
  "timestamp": 1700000000000
}
```

服务端响应：

```json
{
  "type": "auth_success",
  "client_id": "web_1696400000",
  "message": "authentication ok"
}
```

### 请求 Offer

```json
{
  "type": "request_offer",
  "data": {
    "source_id": "camera_01"
  },
  "timestamp": 1700000001000
}
```

若未传 `source_id`，服务端使用该客户端最近一次设置的来源，或默认值。

### 服务端 Offer

```json
{
  "type": "offer",
  "client_id": "web_1696400000",
  "data": {
    "type": "offer",
    "sdp": "v=0\r\no=- 123456 2 IN IP4 127.0.0.1\r\n..."
  },
  "timestamp": 1700000001500
}
```

### 客户端 Answer

```json
{
  "type": "answer",
  "data": {
    "type": "answer",
    "sdp": "v=0\r\no=- 987654 2 IN IP4 127.0.0.1\r\n..."
  },
  "timestamp": 1700000002000
}
```

### ICE Candidate

```json
{
  "type": "ice_candidate",
  "data": {
    "candidate": "candidate:1 1 UDP 2122260223 192.168.1.10 52128 typ host",
    "sdpMid": "0",
    "sdpMLineIndex": 0
  },
  "timestamp": 1700000002500
}
```

客户端和服务端都会发送该消息。若信令失败，服务端可能返回：

```json
{
  "type": "error",
  "error_code": "SIGNALING_ERROR",
  "message": "invalid message format"
}
```

## DataChannel 数据格式

- 通道名称：`video`
- 模式：可靠（Reliable）、有序（Ordered）
- 每帧数据：
  - 前 4 字节：无符号整型（大端序），表示后续 JPEG 数据长度
  - 随后紧跟 JPEG 字节流

示例解析伪代码：

```javascript
function onDataChannelMessage(event) {
  const buffer = event.data; // ArrayBuffer
  const view = new DataView(buffer);
  const length = view.getUint32(0, false); // big-endian
  const jpegBytes = new Uint8Array(buffer, 4, length);
  const blob = new Blob([jpegBytes], { type: 'image/jpeg' });
  imgElement.src = URL.createObjectURL(blob);
}
```

若帧长度超过 16 KiB，服务端会先发送 4 字节帧长头，随后按照 16 KiB 分块、多次发送剩余数据，客户端应持续累积直至凑齐完整 JPEG。

## 端口与服务

| 服务                     | 默认端口 | 说明                              |
|--------------------------|----------|-----------------------------------|
| REST / Analysis API      | 8082     | `/api/subscribe`、`/api/system/*` |
| WebSocket 信令 + DataChannel | 8083     | WebRTC 协商与 JPEG 帧传输          |
| RTSP                    | 8554     | 外部推流示例端口（例如 MediaMTX） |

## 与 REST 控制面的关系

- `/api/subscribe`：创建管线、打开 RTSP 源、启动推理与编码。
- `/api/unsubscribe`：停止并移除管线。
- `/api/pipelines`：查看当前活跃管线和统计数据。

WebRTC 信令组件只负责媒体传输协商，REST 接口负责生命周期管理。若客户端尚未通过 REST 订阅流，即使完成信令，DataChannel 也不会收到画面。

## 常见问题排查

1. **未收到 `auth_success`**：检查客户端是否发送了正确的 JSON，或服务端是否拒绝了连接。
2. **收不到 Offer/Answer**：确认 `/api/subscribe` 已创建对应的管线，并查看服务端日志中是否有信令错误输出。
3. **DataChannel 无数据**：
   - 确认 RTSP 源正常，`VideoAnalyzer` 日志中能看到 “Analysis complete” 记录。
   - 检查前端是否使用大端序解析了 4 字节帧长。
   - 若网络存在 NAT/防火墙，考虑配置 STUN/TURN 或在局域网内联调。
4. **WebSocket 断开**：服务端对异常报文会关闭连接；可在浏览器控制台或服务器日志中查看具体原因。

## 未来计划

- 可选的 STUN/TURN 配置支持。
- 对 DataChannel 帧头添加校验字段，提高异常情况下的恢复能力。
- 提供专门的 REST/WebRTC 协议测试脚本。

---
若您在使用过程中发现协议与实现不一致，请在仓库 Issue 中反馈，或附带日志、报文示例以便快速修复。
