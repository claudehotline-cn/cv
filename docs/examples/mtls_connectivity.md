# 控制平面 mTLS 最小连通性示例（Windows/pwsh）

本示例演示如何在 ControlPlane（CP）侧启用 gRPC 客户端 mTLS，并通过最小探针验证到后端（探针模拟 VA/VSM 服务）的连通性。示例证书与脚本仅用于本地测试，勿用于生产。

## 目录与前提
- 证书生成脚本：`tools/gen_sample_certs.ps1`
- mTLS 探针（gRPC TLS 服务器）：`tools/grpc_mtls_probe`（自动构建）
- 连通性脚本：`tools/test_mtls_connectivity.ps1`
- 需要 OpenSSL（命令 `openssl.exe` 可用），vcpkg 工具链已安装。

## 一键连通性测试

```pwsh
# 生成证书 → 构建探针 → 启动 CP 并自测
pwsh -ExecutionPolicy Bypass -File tools/test_mtls_connectivity.ps1
```

预期输出（摘要）：
- 生成 CA / 服务端证书（va_server/vsm_server）与 CP 客户端证书（cp_client）至 `controlplane/config/certs/`
- 启动 `grpc_mtls_probe.exe`（要求客户端证书）监听 `127.0.0.1:55051`
- 写入 `controlplane/config/app.tls.mtls.sample.yaml` 启用 CP→VA/VSM 的 mTLS
- 启动 `controlplane.exe`（HTTP 监听 `127.0.0.1:18080`）
- 调用 `/api/control/status?pipeline_name=demo` 返回 `200`（通过 mTLS 访问探针）

## 手动步骤（可选）

1) 生成证书
```pwsh
pwsh -ExecutionPolicy Bypass -File tools/gen_sample_certs.ps1
# 输出：controlplane/config/certs/{ca.pem, va_server.*, vsm_server.*, cp_client.*}
```

2) 启动 gRPC mTLS 探针
```pwsh
cmake -S tools/grpc_mtls_probe -B tools/grpc_mtls_probe/build
cmake --build tools/grpc_mtls_probe/build -j
./tools/grpc_mtls_probe/build/bin/grpc_mtls_probe.exe `
  --listen 127.0.0.1:55051 `
  --ca controlplane/config/certs/ca.pem `
  --cert controlplane/config/certs/va_server.crt `
  --key controlplane/config/certs/va_server.key
```

3) 启用 CP mTLS（示例）
在 `controlplane/config/app.yaml` 中追加或参考以下片段（以样例证书为例）：
```yaml
va:
  grpc_addr: 127.0.0.1:55051
  tls:
    enabled: true
    root_cert_file: controlplane/config/certs/ca.pem
    client_cert_file: controlplane/config/certs/cp_client.crt
    client_key_file: controlplane/config/certs/cp_client.key
vsm:
  grpc_addr: 127.0.0.1:55051
  tls:
    enabled: true
    root_cert_file: controlplane/config/certs/ca.pem
    client_cert_file: controlplane/config/certs/cp_client.crt
    client_key_file: controlplane/config/certs/cp_client.key
```

4) 启动 CP 并验证
```pwsh
# 构建 CP，若未构建：tools/build_controlplane_with_vcvars.cmd
./controlplane/build/bin/controlplane.exe controlplane/config
# 访问：
irm -UseBasicParsing "http://127.0.0.1:8080/api/control/status?pipeline_name=demo"
```

> 说明：当前 VSM 相关部分在部分路由仍使用非 TLS 连接；mTLS 验证重点覆盖 VA 控制路径（/api/control/*）。

## 负路径用例（可选）

- 本地：
  - pwsh -ExecutionPolicy Bypass -File tools/test_mtls_negative.ps1
  - 覆盖用例：错误 CA 路径、CA 不匹配（预期 HTTP 502）
- CI 开启：
  - 在 GitHub Actions 环境（或 workflow 级）设置 `CP_MTLS_TEST=1` 即可运行该负路径步骤

## 故障排查
- `openssl.exe` 未找到：请安装 OpenSSL 并加入 PATH；或在 Git Bash/WSL 下执行。
- 状态非 200：检查探针是否启动、`app.yaml` 的地址与证书路径、`client_cert/key` 是否与 `ca.pem` 匹配。
- 生产环境：请使用真实 CA 与证书/密钥，谨慎管理私钥；开启最小必要权限与完善告警。
