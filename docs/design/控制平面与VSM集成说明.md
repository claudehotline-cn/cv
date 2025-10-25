# 控制平面与 Video-Source-Manager 集成说明（阶段A雏形）

本说明简述控制平面（CP，内置于 VA）与视频源管理器（VSM）的集成关系与演进路径。

## 目标

- 以 VA 为执行核心，内置最小可用的控制面能力（gRPC/REST）。
- VSM 负责 RTSP 源管理与健康检查，后续通过 gRPC 与 VA 交互。
- 设计保持开闭原则，后续可演进为独立进程或扩展更多适配器。

## 目录概览

- `video-analyzer/src/control_plane_embedded/`
  - `interfaces.hpp`：Status/OpaquePtr/PlainPipelineSpec/IGraphAdapter/IExecutor 等接口
  - `adapters/graph_adapter_yaml.*`：从 `config/graphs/*.yaml` 解析多阶段图
  - `controllers/pipeline_controller.*`：Apply/Remove/Drain/HotSwapModel/GetStatus
  - `api/grpc_server.*`：AnalyzerControl gRPC 服务
  - `exporters/prometheus_exporter.*`：REST `/metrics`
  - `io/from_vsm_link.hpp`：与 VSM 的数据输入链路（占位，后续可替换为共享内存/IPC/gRPC）

- `video-source-manager/`
  - `proto/source_control.proto`：VSM 的 SourceControl gRPC 定义
  - `src/app/*`：VSM 主程序与适配器

## 说明

- 运行配置（VA，示例）：

```
control_plane:
  enabled: true
  grpc_addr: "0.0.0.0:50051"
  metrics_enabled: true
```

- 构建约束（重要）：自 2025-10-25 起，VA/VSM 构建已强制启用 gRPC/Protobuf，文档中涉及 `USE_GRPC`、`VA_ENABLE_GRPC_SERVER` 的外部开关已废弃；无需也不应再通过 CMake 传入这些开关。

## 下一阶段（B/C）

1) 管理 gRPC 与 Proto
   - `video-analyzer/proto/` 中维护 `analyzer_control.proto`、`pipeline.proto`。
   - CMake 强制 `find_package(Protobuf CONFIG REQUIRED)`、`find_package(gRPC CONFIG REQUIRED)`。
   - 使用 vcpkg 工具链统一依赖版本（`D:/Projects/vcpkg`）。

2) 执行器演进
   - 逐步替换 `SimpleExecutor` 为可扩展的多阶段执行器/Runner，支持热切换与 Drain。

3) VSM 互通
   - VSM 提供 `SourceControl` gRPC，用于源管理与健康检查。
   - 向 VA 暴露的 `ToAnalyzerLink` 可按需要选择共享内存/IPC/gRPC。

