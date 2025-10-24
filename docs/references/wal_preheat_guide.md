# WAL 与预热指南（最小闭环）

## 概览
- 目标：在不改变业务接口的前提下，完成订阅事件 WAL 取证最小闭环与模型注册表预热的基础能力，并对外曝光状态与指标。
- 生效范围：Video Analyzer（VA）后端。

## 启用方式（环境变量）
- WAL（订阅事件）
  - `VA_WAL_SUBSCRIPTIONS=1`（启用）
  - 可选滚动与保留：
    - `VA_WAL_MAX_BYTES=5242880`（活动文件超限滚动，字节数，默认 5MB）
    - `VA_WAL_MAX_FILES=5`（最多保留 N 个已滚动文件，默认 5）
    - `VA_WAL_TTL_SECONDS=0`（大于 0 时对所有 WAL 文件按 TTL 清理）
- 模型注册表预热（ModelRegistry）
  - `VA_MODEL_REGISTRY_ENABLED=1`（启用注册表）
  - `VA_MODEL_PREHEAT_ENABLED=1`（启用预热）
  - `VA_MODEL_PREHEAT_CONCURRENCY=2`（预热并发上限）
  - `VA_MODEL_PREHEAT_LIST=det_a,det_b`（预热名单，逗号/分号/空格分隔）

## 对外接口与状态
- REST：
  - `GET /api/system/info`
    - `wal: { enabled, failed_restart }`
    - `registry.preheat: { enabled, concurrency, list[], status: idle|running|done, warmed }`
  - 管理取证（只读）：
    - `GET /api/admin/wal/summary` → `{ enabled, failed_restart }`
    - `GET /api/admin/wal/tail?n=200` → `{ count, items[] }`（活动文件尾部）
- 指标（/metrics）：
  - WAL：`va_wal_failed_restart_total`
  - 预热：
    - `va_model_preheat_enabled`、`va_model_preheat_concurrency`、`va_model_preheat_warmed_total`
    - `va_model_preheat_duration_seconds_bucket{le=...}`、`_sum`、`_count`
    - `va_model_preheat_failed_total`
  - 订阅分阶段直方图：
    - `va_subscription_phase_seconds_bucket{phase=opening_rtsp|loading_model|starting_pipeline,le=...}`、`_sum`、`_count`

## 运行示例（Windows, pwsh）
```
# 构建
& tools/build_va_with_vcvars.cmd

# 启动并启用 WAL 与预热（示例）
$env:VA_WAL_SUBSCRIPTIONS='1'
$env:VA_MODEL_REGISTRY_ENABLED='1'
$env:VA_MODEL_PREHEAT_ENABLED='1'
$env:VA_MODEL_PREHEAT_CONCURRENCY='2'
Start-Process 'video-analyzer/build-ninja/bin/VideoAnalyzer.exe' 'video-analyzer/build-ninja/bin/config'

# 验证健康与指标
Invoke-RestMethod http://127.0.0.1:8082/api/system/info | ConvertTo-Json -Depth 6
Invoke-RestMethod http://127.0.0.1:8082/metrics | Out-String
```

## 取证建议
- 订阅事件写入 `logs/subscriptions.wal`（JSONL）。
- 发版/复现问题时：
  - 先访问 `GET /api/admin/wal/summary` 记录 `failed_restart`。
  - 必要时抓取 `GET /api/admin/wal/tail?n=200` 并随同日志上报。

> 说明：当前 WAL/预热为“最小可用”骨架，默认关闭；在高基数场景下请谨慎增加指标维度标签，避免 Prometheus 卡顿或高内存占用。

