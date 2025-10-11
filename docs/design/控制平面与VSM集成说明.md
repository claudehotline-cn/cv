# 控制平面与 Video-Source-Manager 集成说明（阶段A骨架）

本次改造目标：将后端拆分为“控制平面（暂内嵌）+ video-analyzer（执行面）+ video-source-manager（VSM）”。当前提交实现了最小骨架，兼容现有功能，不引入额外运行时依赖。

## 目录与组件

- `video-analyzer/src/control_plane_embedded/`
  - `interfaces.hpp`：Status、OpaquePtr、PlainPipelineSpec、IGraphAdapter/IExecutor 接口。
  - `adapters/graph_adapter_yaml.*`：基于 `config/graphs/*.yaml` 构建 Multistage Graph，返回 SimpleExecutor（生命周期管理占位）。
  - `controllers/pipeline_controller.*`：控制 Apply/Remove/Drain/HotSwapModel/GetStatus。
  - `api/grpc_server.*`：gRPC 占位（未启用时返回空句柄，后续接入 gRPC/Proto）。
  - `exporters/prometheus_exporter.*`：Prometheus 导出占位，后续接入 REST `/metrics`。
  - `io/from_vsm_link.hpp`：与 VSM 的桥接占位，后续替换为共享内存/IPC/gRPC 流。

- `video-source-manager/`（骨架，未参与构建）
  - `proto/source_control.proto`：Attach/Detach/GetHealth（根据参考设计文档）。
  - `README.md`、`src/app/main.cpp`：占位。

## 配置

- `video-analyzer/config/app.yaml` 新增：

```
control_plane:
  enabled: false
  grpc_addr: "0.0.0.0:50051"
  metrics_enabled: false
```

默认关闭控制平面与 gRPC，保持行为稳定。后续接入 gRPC 时可通过该段配置启用。

## 构建

- 不引入 gRPC/Protobuf 依赖，所有新增代码均可直接编译链接。
- CMake 已加入 control_plane_embedded 源文件；proto 文件暂作为参考，不参与生成。

## 下一步（阶段B/C）

1) 接入 gRPC 与 Proto
   - 在 `video-analyzer/proto/` 放置 `analyzer_control.proto`、`pipeline.proto`，CMake 增加可选 `USE_GRPC`。
   - `grpc_server` 替换为真实服务，将 RPC 转发到 `PipelineController`。

2) 执行面耦合完善
   - `SimpleExecutor` 替换为真正的执行器（与媒体管线/Runner 对接），支持热切模型与 Drain。

3) VSM 落地
   - 完成 `video-source-manager` 的最小服务：`SourceControl` gRPC 与 FFmpeg RTSP 适配。
   - `ToAnalyzerLink` 替换为高效通道（共享内存/IPC/gRPC 流）。

