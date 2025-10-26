# CONTEXT（统一背景与当前共识）

更新时间：2025-10-25

本文件汇总本轮对话中达成的关键结论：代码组织、命名与构建策略、gRPC 依赖与控制平面职责边界、已完成工作与后续计划。用于团队对齐与后续实施的“唯一事实来源”。

## 项目结构与职责

- video-analyzer（VA）：核心后端（RTSP 接入、预处理/推理/后处理、WHEP/HLS、REST/指标）。
  - 内嵌控制面 gRPC 服务保留在 VA 进程（AnalyzerControl）。
- controlplane（CP）：对外唯一 REST/SSE 服务面，聚合/代理到 VA、VSM 的 gRPC；前端只与 CP 通信。
- video-source-manager（VSM）：视频源管理（SourceControl gRPC：WatchState/GetHealth/Update/Attach/Detach）。
- web-front：管理/预览 UI。

目录命名统一：
- 根目录 controlplain → controlplane（可执行：`controlplane/build/bin/controlplane.exe`）。
- VA 内嵌控制面目录：`video-analyzer/src/control_plane_embedded` → `video-analyzer/src/controlplane`（全量修正 include 与 CMake 源列表）。

## 构建与依赖（Windows）

- 统一使用 vcpkg 工具链，禁止使用 Anaconda 库。
  - VA：`tools/configure_va_nv.bat` 指定 `-DCMAKE_TOOLCHAIN_FILE` 与 `D:\Projects\vcpkg`，屏蔽 `H:\anaconda3`；构建产物：`video-analyzer/build-ninja/bin/VideoAnalyzer.exe`。
  - VSM：`tools/build_vsm_with_vcvars.cmd` 清理 `-DUSE_GRPC` 开关，使用 vcpkg。
  - CLI：`tools/build_cli.bat` 清理 `-DUSE_GRPC`，使用 vcpkg。
  - CP：`tools/build_controlplane_with_vcvars.cmd`（新增）统一配置+构建。

gRPC/Protobuf 策略：
- VA 强制启用 `find_package(Protobuf CONFIG REQUIRED)`、`find_package(gRPC CONFIG REQUIRED)`；CMake 内部定义 `USE_GRPC`/`VA_ENABLE_GRPC_SERVER`；外部开关已废弃。
- 依赖解析优先 vcpkg（OpenSSL/Zlib/Protobuf/gRPC/RE2/c-ares 等）。

## controlplane 当前能力与差距

已实现（controlplane/src/server/main.cpp）：
- HTTP/CORS 基础；`/api/system/info` 聚合（2s 缓存，best-effort）
- 订阅最小能力：`/api/subscriptions`（POST 受理 202+Location，GET 支持 ETag/304，DELETE 幂等）
- 源管理起步：`/api/sources`（优先 WatchState 快照，回退 GetHealth），`/api/sources:enable|disable`
- SSE 适配器：`CP_FAKE_WATCH=1` 时输出示例流；VA Watch 就绪后可桥接 gRPC→SSE

待完善：
- `/api/subscriptions/:id/events` SSE 接 VA Watch（gRPC 流）；
- `/api/control/*`（apply/apply_pipelines/hotswap/pipeline/status/drain）转发到 VA AnalyzerControl；
- `/api/orch/*` 编排到 VSM/VA；
- 统一错误语义（gRPC→HTTP）、安全（CORS 白名单/Token/mTLS）、限流/熔断、指标与告警。

## VA 侧“保留/迁移”边界

- 迁移到 CP（对外）：`/api/subscriptions*`（含 SSE）、`/api/system/info`、`/api/sources*`、`/api/control/*`、`/api/orch/*`。
- 保留在 VA（内部/底层）：`/metrics`、`/api/admin/wal/*`、`/api/db/*`、媒体/WHEP 路径（`video-analyzer/src/server/rest_whep.cpp`）。

## 已完成关键变更（本轮）

- 目录重命名与构建验证：
  - controlplain → controlplane；VA 内嵌控制面目录改名；所有 include/CMake 修正；两端均构建通过。
- 构建脚本与依赖：
  - 全面切换 vcpkg；移除/清理 `-DUSE_GRPC`、`-DVA_ENABLE_GRPC_SERVER` 等无效参数；屏蔽 Anaconda 路径。
- 最小冒烟：
  - VA 监听 `9090/50051` 验证通过；CP `tools/run_cp_smoke.ps1` 通过（部分后端缺失用例 SKIP，`/api/system/info` PASS）。

## 下一步计划（摘录）

- M0：补齐 `/api/control/*` 映射、错误/指标规范、gRPC 客户端重试/超时。
- M1：`/api/sources` watch（SSE）与 Restream 完整闭环（`source_id→rtsp_base+id`）。
- M2：SSE 桥接（VA Watch）、安全（CORS 白名单、Token/mTLS）、限流/熔断、Grafana 告警。

## 依赖与环境

- 外部：gRPC/Protobuf/OpenSSL/Zlib/RE2/c-ares（vcpkg），CUDA（可选），MySQL/Redis（测试），RTSP 源（`rtsp://127.0.0.1:8554/camera_01`）。
- 内部：VA AnalyzerControl gRPC、VSM SourceControl gRPC；前端仅接入 CP。

## 安全基线（默认关闭，配置可控）

- CORS 白名单：`security.cors.allowed_origins` 支持 `"*"` 或指定 Origin 列表；动态回显 `Access-Control-Allow-Origin`。
- Bearer Token：`security.auth.bearer_token` 非空时开启校验；`/metrics` 默认豁免。
- 简单限流：`security.rate_limit.rps` 为每路由每秒的上限；0 关闭。

示例（controlplane/config/app.yaml）：

```yaml
security:
  cors:
    allowed_origins: ["http://127.0.0.1:3000"]
  auth:
    bearer_token: "your_token"
  rate_limit:
    rps: 50
```
