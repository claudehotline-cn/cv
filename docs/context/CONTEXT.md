# 上下文梳理与 TLS/mTLS 统一（最新）

本文整理当前对话与实现：统一 CP/VA/VSM 的 TLS/mTLS 配置来源与证书路径，修复 “wrong version number/UNAVAILABLE/peer did not return a certificate” 等握手问题；完成 VSM→VA 的编排改造（改为 gRPC + mTLS）；并记录 VA 零拷贝路径调试要点与最小化取证流程。

## 架构与职责
- Controlplane（CP）：对外 REST/SSE；作为 VA/VSM 的 gRPC 客户端；默认启用 TLS/mTLS。
- Video Analyzer（VA）：RTSP→预处理→推理→后处理→WebRTC/HLS；gRPC Server 默认 TLS/mTLS；前端通过 WHEP（禁止 fallback）。
- Video Source Manager（VSM）：管理 RTSP 源；gRPC Server 默认 TLS/mTLS；对 VA 进行编排（已由 REST 改为 gRPC）。
- Web-front：仅与 CP 交互；WHEP 直连 VA 观看流与叠加层。

## TLS/mTLS 统一方案
- 全部使用各自 `config/app.yaml`，不再依赖环境变量；相对路径基于“配置目录”解析为绝对路径。
- 证书放置规范（均在 `config/certs/`）：
  - CA：`ca.pem`
  - VA：`va_server.crt`/`va_server.key`，可选 `va_client.crt`/`va_client.key`
  - VSM：`vsm_server.crt`/`vsm_server.key`
  - CP 客户端：`cp_client.crt`/`cp_client.key`
- SNI/Authority：所有 gRPC 客户端设置 `grpc.ssl_target_name_override=localhost` 与 `grpc.default_authority=localhost`，匹配证书 SAN（DNS:localhost, IP:127.0.0.1）。
- 代码落实：
  - CP：`controlplane/src/server/config.cpp` 绝对化 `va.tls`/`vsm.tls`；`grpc_clients.cpp` 设置 SNI。
  - VA：`src/ConfigLoader.cpp` 在 `control_plane.tls` 下绝对化证书路径；gRPC Server 从应用配置读取；VA 可用 `va_client` 证书进行出站 mTLS。
  - VSM：新增 `src/app/config.{hpp,cpp}`（支持 `server.grpc_listen`、`tls.*` 与 `va.{addr,tls.*}`）；`main` 支持传入配置目录；`source_agent.cc` 改为调用 VA gRPC（mTLS），彻底移除 env fallback。

## 关键问题与解决
- 错误 `wrong version number`：常见于一端非 TLS 或 SNI 不匹配；统一改为配置驱动 + SNI=localhost。
- 错误 `peer did not return a certificate`：对端未配置/未发送客户端证书；开启 mTLS，并在 `require_client_cert` 下核对客户端证书路径。
- `unexpected eof while reading`：使用 openssl 直连 gRPC 端口的常见现象，非握手失败；以 gRPC 客户端状态与服务日志为准。
- VA 零拷贝：
  - 现象：`[RuntimeSummary][post-open] provider=cpu`、`post.yolo.nms` 失败。
  - 处置：`NodeModel` 读取引擎 `allow_cpu_fallback/use_io_binding`，默认禁用 CPU 回退；确保 GPU IoBinding、生效后在日志中应见 `gpu_active=1, io_binding=1`。

## 配置与启动
- VA：`video-analyzer/build-ninja/bin/VideoAnalyzer.exe video-analyzer/build-ninja/bin/config`
- VSM：`video-source-manager/build/bin/VideoSourceManager.exe video-source-manager/config`
- CP：`controlplane/build/bin/controlplane.exe controlplane/config`
说明：修改 TLS 配置后需重启三后端；不要清理构建目录。

## 编排与测试
- VSM → VA：
  - `POST /api/orch/attach_apply` → VA gRPC `ApplyPipeline`（mTLS）。
  - `POST /api/orch/detach_remove` → VA gRPC `RemovePipeline`（mTLS）。
- 前端联调：Chrome DevTools MCP 最小取证（清单≤10条，结构化 JSON），截图落盘；WHEP 201，video `readyState≥2`。
- 健康度：
  - 端口监听/HTTP 可达；VA `/metrics`；CP 后端错误分布 by(service,method,code) 有数据。

## 待办与风险提示
- 重建并重启三后端以落地上述改动。
- 校验模型输出名/形状与 multistage graph（`analyzer_multistage_example.yaml`）一致，避免 NMS 失败。
- 如 CUDA EP 环境不完整，禁用 CPU 回退会让问题显性化，便于定位（缺少 CUDA DLL/驱动、ONNXRuntime CUDA 构建等）。

## 参考
- 开发证书脚本：`tools/gen_dev_certs.ps1`（含 SAN: localhost/127.0.0.1）。
- 测试 RTSP 源：`rtsp://127.0.0.1:8554/camera_01`。

