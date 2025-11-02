# 计算机视觉视频分析系统（总体说明）

本仓库承载一个面向实时视频分析的端到端方案，按“解耦、可替换、可观测”的原则设计，围绕三大子项目协同工作：

- video-analyzer（C++）：后端分析引擎。拉取 RTSP 流、执行 ONNX/TensorRT 推理、叠加结果并通过 WebRTC DataChannel 实时推送到前端；提供 REST 控制面（订阅、模型切换、状态查询）。
- web-frontend（TS/Vue）：前端应用。接入信令与 DataChannel，播放分析后的视频帧，提供订阅、参数调节等交互能力。（与本仓库解耦，代码可能位于独立目录/仓库）
- video-source-manager（可选）：视频源编排与资产管理（如 RTSP 源目录、健康检查、批量启停等）。当前顶层构建默认未纳入，如需可单独启用或独立部署。

系统既可在单机完成 PoC，也可扩展为生产级的多实例部署（解耦的控制/媒体平面、可横向扩展的分析节点、集中观测）。

## 架构总览

数据平面：RTSP（输入）→ 解码/推理/渲染 → WebRTC DataChannel（JPEG 帧）
控制平面：HTTP/JSON（REST）驱动管线生命周期与配置

```
┌────────────────────┐     RTSP     ┌────────────────────┐      WebRTC/DC      ┌───────────────────┐
│  Cameras/Streams   ├──────────────▶  video-analyzer    ├──────────────────────▶  web-frontend     │
│ (rtsp://...:8554)  │              │  (C++)             │  (offer/answer/ICE)  │ (Vue/TS)          │
└────────────────────┘              │  REST :8082        │                      └───────────────────┘
                                    │  WS   :8083        │
                                    └────────────────────┘
         ▲                                       ▲
         │ REST /api/subscribe /api/pipelines    │ metrics/logs
         └───────────────────────────────────────┘
```

- 控制面（8082）：/api/subscribe、/api/unsubscribe、/api/models、/api/system/*
- 信令面（8083）：WebSocket 交换 auth、request_offer、offer/answer、ice_candidate
- 媒体面：DataChannel 可靠有序传输，数据格式为“4 字节帧长（大端）+ JPEG 数据”（详见 docs/webrtc-protocol.md）

## 设计理念
- 模块解耦：Source/Analyzer/Encoder/Transport/Server 分层，单一职责、便于替换
- 可观测：统一日志与轻量化统计，REST 暴露运行指标
- 性能优先：合理的预处理/后处理与 NMS；支持 CUDA/TensorRT（含 IOBinding 预留）
- 渐进式复杂度：先打稳 CPU/GPU 推理链路，再引入 WHIP/WHEP、TURN/STUN 等高级能力

## 仓库结构
```
video-analyzer/                # C++ 后端分析引擎（当前唯一默认构建的子项目）
├── CMakeLists.txt
├── config/                    # app.yaml / profiles.yaml / models.yaml / analyzer_params.yaml
├── include/                   # （公开头，多为内部模块使用）
├── src/
│   ├── analyzer/              # 预处理、模型会话（ONNX Runtime）、后处理（YOLOv12 等）、渲染
│   ├── app/                   # Application & 引导
│   ├── core/                  # 工厂、管线管理、日志等
│   ├── media/                 # RTSP 源、H264 编码器（FFmpeg）、WebRTC DataChannel 传输
│   └── server/                # REST Server（最小实现，支持跨域/简单路由）
└── test/
    └── scripts/               # 调试/回归脚本（REST 校验、订阅流程、日志分析）

docs/                          # 设计与协议文档
└── webrtc-protocol.md         # WebRTC 信令与 DataChannel 协议约定

CMakeLists.txt                 # 顶层仅 add_subdirectory(video-analyzer)
```

> 说明：web-frontend 与 video-source-manager 可位于同仓或独立仓库；本 README 面向系统整体，但当前顶层构建只包含 video-analyzer。

## 快速开始（单机）
1) 准备依赖
- CMake ≥ 3.16，MSVC 2022（Windows）或 GCC/Clang（Linux/macOS）
- OpenCV（带 FFmpeg 支持）
- yaml-cpp（仓库内 third_party 可用）
- ONNX Runtime（GPU 版本可选，需与本机 CUDA/TensorRT 兼容）

2) 构建后端
```
cd video-analyzer
mkdir build && cd build
cmake .. -A x64
cmake --build . --config Release
```
生成物：`video-analyzer/build/bin/Release/VideoAnalyzer.exe`

3) 准备配置与视频源
- `video-analyzer/config/*.yaml`（已提供默认模板）
- 启动 RTSP（如 MediaMTX）并推流到 `rtsp://127.0.0.1:8554/camera_01`

4) 运行后端
```
cd video-analyzer/build/bin/Release
./VideoAnalyzer.exe ../../config/app.yaml
```
默认端口：REST 8082，WebSocket/信令 8083

5) 订阅一个流
- POST http://127.0.0.1:8082/api/subscribe 传入 stream, profile, url
- GET  http://127.0.0.1:8082/api/pipelines 查看是否已创建

6) 前端或调试脚本联接信令（8083），完成 offer/answer/ICE，建立 DataChannel 后即可接收 JPEG 帧

> 辅助脚本见 video-analyzer/test/scripts/：check_analysis_api.py、check_subscription_flow.py、analyze_detection_log.py

## 配置说明（概要）
- app.yaml：执行引擎（CPU/CUDA/TRT）、日志、观测等全局选项
- models.yaml：模型清单，含家族/变体、模型路径、默认输入尺寸
- profiles.yaml：输出编码与发布参数（编码器、分辨率、码率、WHIP/WHEP 预留等）
- analyzer_params.yaml：阈值、类别过滤等运行时参数

## 子项目简述
- video-analyzer：核心后端（C++，本仓库默认构建）。
- web-frontend：浏览器端应用（Vue/TS），负责 UI、信令与帧展示；可单独构建/部署。
- video-source-manager（可选）：视频源资产与编排服务（REST）。短期内不纳入默认构建，建议独立服务化。

## API 与协议
- REST：/api/subscribe、/api/unsubscribe、/api/pipelines、/api/models、/api/system/*
- WebRTC：信令消息与 DataChannel 帧格式详见 docs/webrtc-protocol.md

## 观测与调试
- 日志：结构化/分级日志（文件与控制台开关可通过配置控制）
- 指标：管线 FPS、延迟、传输字节与包数；可从 /api/system/stats 获取
- 常见问题：RTSP 丢包、DataChannel 未收到帧、CUDA 不兼容（见 webrtc-protocol 与 README“快速开始”）

## 启动与测试（TLS）
- 一键启动后端栈（VSM/VA/CP，TLS）：
  - `pwsh tools/start_stack_tls.ps1 -KillExisting`
- 控制平面冒烟（TLS）：
  - `pwsh tools/run_cp_smoke.ps1 -BaseUrl http://127.0.0.1:18080 -CfgDir controlplane/config`
- mTLS 连通性回归：
  - `pwsh tools/test_mtls_connectivity.ps1`
  - `pwsh tools/test_mtls_negative.ps1`
- SSE Soak（2 分钟示例）：
  - `pwsh tools/run_cp_sse_soak_tls.ps1 -Sec 120`

## 路线图（Roadmap）
- WHIP/WHEP（RFC 9725）对接与可选替换 DataChannel 路径
- STUN/TURN 与公网穿透
- IOBinding/TensorRT 性能优化、自适应 Batch 或分片
- 更完善的 API 文档与前端组件示例

## 贡献
欢迎提交 Issue / PR：
- 变更 REST/信令协议时，请同步更新 docs/webrtc-protocol.md
- 新增脚本/配置时，补充 README 或 docs 使用说明
- 提交前请确保 cmake --build . --config Release 通过

## 更多文档（快速链接）
- TLS 一键化与说明：`docs/README-TLS-一键化.md`
- 上下文摘要：`docs/context/CONTEXT.md`
- 路线图：`docs/context/ROADMAP.md`
- VA→CP REST 迁移指南：`docs/plans/va_rest_迁移指南.md`
