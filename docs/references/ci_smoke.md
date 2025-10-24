# 本地 CI Smoke（WAL/预热）

## 脚本
- `tools/run_ci_smoke.ps1`
  - 构建 VA（`tools/build_va_with_vcvars.cmd`）
  - 启动一次 VA 并执行：`check_admin_wal_endpoints.py`
  - 执行：`check_preheat_status.py`（内部自启/自停 VA）
  - 执行：`check_wal_scan.py`（内部自启/自停 VA）

## 运行
```
# Windows PowerShell
& tools/run_ci_smoke.ps1
```

## 预期输出（节选）
```
== Build VideoAnalyzer ==
== Test 1: admin WAL endpoints (baseline server) ==
admin wal endpoints: OK
== Test 2: model registry preheat status ==
preheat status: OK
== Test 3: WAL scan after restart ==
wal scan: OK (failed_restart= 0 )
All smoke tests passed.
```

## 注意
- 脚本默认访问 `http://127.0.0.1:8082`。
- 若环境中已有 VA 正在运行，脚本会在必要时停止并重启以避免端口占用。
- `check_metrics_exposure.py`/`check_headers_cache.py` 依赖第三方包 `requests`，可按需在 CI 阶段另外运行。

