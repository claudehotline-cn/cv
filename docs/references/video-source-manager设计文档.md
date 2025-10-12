好的！下面给你两套**可直接落地的代码目录**（到源文件级别），语言以 **C++17/20 + CMake + gRPC/Proto** 为基础；**不引入数据库与 Nacos**，但在目录中保留清晰的“端口/适配器（Ports/Adapters）”扩展点，后期可以把控制平面从 `video-analyzer` 项目中**无缝剥离**为独立服务（只需替换少量适配器实现）。

------

# 一、`video-source-manager/`（仅做“视频源接入与分发”的 Agent）

```
video-source-manager/
├─ CMakeLists.txt
├─ README.md
├─ third_party/                         # 可选：httplib.h、prometheus-cpp（header-only 版）、FFmpeg wrapper 等
│   └─ README.md
├─ proto/
│   └─ source_control.proto             # gRPC：控制平面/Analyzer 调用本服务的 Attach/Detach/GetHealth
├─ src/
│  ├─ main.cpp                          # 进程入口，装配 SourceAgent，启动 gRPC Server 和 /metrics
│  ├─ app/
│  │   ├─ source_agent.h
│  │   └─ source_agent.cc               # 进程生命周期、配置装载、信号处理、组件启动/停止
│  │
│  │   ├─ controller/
│  │   │   ├─ source_controller.h
│  │   │   └─ source_controller.cc      # 处理 Attach/Detach、路由到具体输入→输出管道，维护会话表
│  │   │
│  │   ├─ health/
│  │   │   ├─ health_monitor.h
│  │   │   └─ health_monitor.cc         # 心跳/RTT/抖动/重连策略（内存状态），周期性上报给 metrics
│  │   │
│  │   ├─ metrics/
│  │   │   ├─ metrics_exporter.h
│  │   │   └─ metrics_exporter.cc       # /metrics（Prometheus 文本曝光），低依赖：基于 httplib 单文件实现
│  │   │
│  │   └─ rpc/
│  │       ├─ grpc_server.h
│  │       ├─ grpc_server.cc            # 实现 proto::SourceControlService（Attach/Detach/GetHealth）
│  │       ├─ analyzer_client.h
│  │       └─ analyzer_client.cc        # （可选）向 analyzer 发控制/探活（保留扩展：后期可删/替换）
│  │
│  ├─ adapters/
│  │   ├─ inputs/
│  │   │   ├─ ffmpeg_rtsp_reader.h
│  │   │   └─ ffmpeg_rtsp_reader.cc     # RTSP 拉流（FFmpeg，线程安全拉帧，带抖动缓冲）
│  │   │   # 预留其它协议：
│  │   │   ├─ whip_publisher.h          # 未来：WHIP 推流/转发（占位）
│  │   │   └─ whip_publisher.cc
│  │   └─ outputs/
│  │       ├─ to_analyzer_link.h
│  │       └─ to_analyzer_link.cc       # 向 analyzer 送帧（共享内存/本地环形队列/或 gRPC 流；此处放本地环形队列占位）
│  │
│  ├─ config/
│  │   ├─ config.h
│  │   └─ config.cc                     # 仅内存配置（JSON/YAML 解析），预留 IConfigStore 以便未来接 DB/Nacos
│  │
│  └─ util/
│      ├─ logging.h
│      ├─ logging.cc                    # spdlog/minilog 封装
│      ├─ thread_pool.h
│      ├─ thread_pool.cc
│      ├─ ring_buffer.h
│      └─ ring_buffer.cc                # 零拷贝/少拷贝环形队列骨架（可落地到共享内存适配器）
├─ include/                             # 对外可见头（目前可空；预留 SDK 化）
│   └─ vsm_export.h
└─ tests/
    ├─ CMakeLists.txt
    └─ source_controller_test.cc
```

**关键文件示例**

`proto/source_control.proto`（最小服务）

```
syntax = "proto3";
package vsm.v1;

service SourceControl {
  rpc Attach(AttachRequest) returns (AttachReply);
  rpc Detach(DetachRequest) returns (DetachReply);
  rpc GetHealth(GetHealthRequest) returns (GetHealthReply);
}

message AttachRequest {
  string attach_id   = 1;   // 幂等键
  string source_uri  = 2;   // rtsp://...  或 future: whip://...
  string pipeline_id = 3;   // 下游标识（供路由或计数）
  map<string,string> options = 4; // 拉帧配置：fps/解码器/超时等
}
message AttachReply { bool accepted = 1; string msg = 2; }

message DetachRequest { string attach_id = 1; }
message DetachReply { bool removed = 1; string msg = 2; }

message GetHealthRequest {}
message GetHealthReply {
  repeated StreamStat streams = 1;
}
message StreamStat {
  string attach_id = 1;
  double fps       = 2;
  double rtt_ms    = 3;
  double jitter_ms = 4;
  double loss_pct  = 5;
  string phase     = 6;   // Ready/Connecting/Backoff/Failed
}
```

`src/app/controller/source_controller.h`（接口骨架）

```
class SourceController {
public:
  bool Attach(const AttachRequest& req, std::string* err);
  bool Detach(const std::string& attach_id, std::string* err);
  std::vector<StreamStat> Collect();
private:
  struct Session {
    std::unique_ptr<FfmpegRtspReader> reader;
    std::shared_ptr<ToAnalyzerLink>   sink;
    std::atomic<bool> running{false};
  };
  std::mutex mu_;
  std::unordered_map<std::string, Session> sessions_; // attach_id -> Session
};
```

`src/adapters/outputs/to_analyzer_link.h`（扩展点）

```
// 目前实现：本机内存队列（后续可替换为 SHM / GPUDirect / gRPC streaming）
class ToAnalyzerLink {
public:
  bool Push(const AVFrame* frame); // 简化为 RGB/BGR/或压缩码流；根据你的 analyzer 接口再细化
};
```

**扩展性说明**

- **配置存储接口**：`config/` 未来替换为 `IConfigStore`（DB/Nacos 实现）。
- **下行链路**：`ToAnalyzerLink` 可替换为**共享内存+信号量**（本机最快），或**gRPC 流**（跨机）。
- **协议适配**：`inputs/` 子目录继续增 `rtmp_reader/whip_reader/...`，`SourceController` 不变。