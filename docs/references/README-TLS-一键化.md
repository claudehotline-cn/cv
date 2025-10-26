# TLS 一键启动与验证指南

> 目标：一键启动 TLS 模式的 VSM/VA/CP，全链路自检（正向/负向/连通性/SSE）。

## 一键启动/停止
- 启动（TLS）：
  - `pwsh tools/start_stack_tls.ps1`
  - 输出示例：`VSM_PID=... VA_PID=... CP_PID=...`
  - 端口：CP `http://127.0.0.1:18080`，VA gRPC `127.0.0.1:50051`，VSM gRPC `127.0.0.1:7070`
- 停止：
  - `pwsh tools/stop_stack.ps1`

## 自检脚本（建议顺序）
- 控制面冒烟（非 Min，TLS 配置）：
  - `pwsh tools/run_cp_smoke.ps1 -BaseUrl http://127.0.0.1:18080 -CfgDir controlplane/config`
  - 覆盖：最小 API、控制接口（apply/drain/delete/hotswap）、编排正路径（独立脚本）、编排负路径（默认启用）、SSE 并发、指标与审计
- mTLS 连通性：
  - 正向：`pwsh tools/test_mtls_connectivity.ps1`
  - 反向：`pwsh tools/test_mtls_negative.ps1`
- SSE Soak（TLS）：
  - `setx CP_SSE_SOAK_SEC 120`（或临时 `$env:CP_SSE_SOAK_SEC='120'`）
  - `python controlplane/test/scripts/soak_cp_sse_watch.py`

## 前端（路由与降级）
- 已默认：`.env.development`/`.env.production`
  - `VITE_API_BASE=http://127.0.0.1:18080`
  - `VITE_CP_BASE_URL=http://127.0.0.1:18080`
- 验证：
  - `pwsh tools/verify_front_routing.ps1` → 确认环境指向 CP
  - 停止 VSM 后 `python tools/verify_cp_sse_degrade.py` → 看到 SSE 初始/keepalive（前端有轮询兜底）

## 证书
- 使用 `tools/gen_sample_certs.ps1` 生成示例证书；本仓库默认使用 `controlplane/config/certs` 下样例（mTLS）。

## 常见问题
- 控制面端口占用/进程未退出：执行 `pwsh tools/stop_stack.ps1` 后重试再启动。
- VSM/VA 链接错误（LNK1104）：执行停止脚本后重建；或使用 `tools/build_vsm_with_vcvars.cmd` 等原地构建脚本。
- mTLS 正向失败：确保 `tools/grpc_mtls_probe/build/bin/grpc_mtls_probe.exe` 存在；若缺失，请先在 CI 或本地执行 CMake 构建。

