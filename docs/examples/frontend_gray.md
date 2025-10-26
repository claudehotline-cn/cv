## 前端切换与灰度（指引）

目标：在不影响用户的前提下，将前端 `baseURL` 灰度切换至 Controlplane（CP），并保留快速回滚能力。

### 步骤
- 配置 CP 基地址（示例）：`http://127.0.0.1:18080`
- 在前端配置（如 `.env` 或前端统一请求封装处）增加可切换项：
  - `VITE_API_BASE`（或等价变量），默认指向 VA 原 REST；灰度时指向 CP。
  - 保留回退开关（如 `VITE_API_FALLBACK=va`）。
- 建议：将 CP 仅暴露对外网关；VA REST 仅在内网或通过开关启用。

### 方案建议
- 按路由分级灰度：优先将 `/api/system/info`、`/api/subscriptions*`、`/api/sources*` 切换至 CP；
  - 观察：RPS、5xx 占比、SSE 连接/重连、请求 P95 延迟；
  - 发现异常即回滚该路由流量到 VA。
- 保留 CP→VA 直通代理开关（如在 CP 增加透传路由），以便前端无需变更即可回退。

### 排查与回滚
- 排查：使用 `X-Correlation-Id` 将前端请求与 CP 审计日志串联；Grafana 面板关注 `cp_request_duration_ms_*` 与 `cp_backend_errors_total`。
- 回滚：前端将 `VITE_API_BASE` 切回 VA REST；或开启 CP 透传开关以过渡。

### 演练脚本（示例指令）
```powershell
# 启动后端（VSM/VA）与 CP（无 TLS）
pwsh -NoProfile -File tools/start_backends.ps1
pwsh -NoProfile -File tools/run_min_cp_tests.ps1 -BaseUrl http://127.0.0.1:18080 -CfgDir controlplane/config-notls

# 前端本地开发时，将 baseURL 置为 CP，并启动 dev 服务器
# setx VITE_API_BASE http://127.0.0.1:18080  # 视前端框架而定
# npm run dev
```
