# 日志与运行时开关（Logging & Runtime Controls）

本篇说明 VideoAnalyzer 的日志系统与相关运行时开关，包含：
- 日志等级、格式、输出与文件滚动配置
- 模块级别日志控制（module_levels）
- 运行时 REST 接口：查询与动态调整日志
- 与指标（/metrics）相关的运行时开关说明

## 配置入口（app.yaml → observability）

位置：`video-analyzer/config/app.yaml`

示例：

```yaml
observability:
  log_level: info           # 全局等级：trace/debug/info/warn/error
  log_format: text          # text 或 json（也可用 VA_LOG_FORMAT 环境变量覆盖）
  console: true             # 控制台输出开关
  file:
    path: logs/va.log       # 日志文件路径（可选）
    max_size_kb: 10240      # 单文件最大大小（KB），0 关闭滚动
    max_files: 5            # 保留历史滚动文件个数

  # 模块级别日志（二选一）：
  module_levels: "transport.webrtc:debug,encoder.ffmpeg:info"
  # modules:
  #   transport.webrtc: debug
  #   encoder.ffmpeg: info

  # 指标导出相关（只列运行时开关，指标清单见 METRICS.md）：
  metrics:
    registry_enabled: true  # 启用统一导出（推荐）；false 使用兼容路径
    extended_labels: false  # 可选扩展标签：decoder/encoder/preproc
    ttl_seconds: 300        # 每源指标条目的 TTL（秒），<=0 表示不清理
```

说明：
- `log_level` 支持：trace、debug、info、warn（warning）、error（err）。
- `log_format` 支持 text/json。也可以通过环境变量 `VA_LOG_FORMAT` 在启动时覆盖。
- `module_levels` 可用字符串（逗号分隔 `模块:等级`）或对象（map）。
- 文件滚动：打开文件写入时，超过 `max_size_kb` 会进行滚动，最多保留 `max_files` 个历史文件。
- `metrics.ttl_seconds` 控制 per-source 指标分片的清理窗口，用于回收不再活跃的源条目（详见下文“源条目回收/TTL”）。

## 源条目回收 / TTL（per-source 资源清理）

- DropMetrics、SourceReconnects、NvdecEvents 等 per-source 指标使用分片结构（16 片）缓存，每个源条目携带 `last_seen_ms`。
- 当 `/metrics` 汇总时，将按 `observability.metrics.ttl_seconds` 清理超过 TTL 未更新的条目，避免长时间运行的进程中内存/标签累积。
- 资源释放路径：
  - 正常退订或超时回收：TrackManager 在 `unsubscribe()` 与 `reapIdle()` 中会同时调用 `unmapUri()` 将 `uri→source_id` 映射移除。
  - 切源：仅在切换成功后，先 `unmap(old_uri)` 再 `map(new_uri)`，保证指标归属正确。
  - 进程退出：TrackManager 析构时会停止 pipeline 并清理 `uri` 映射。

> 注意：将 `ttl_seconds` 设为 0 或负值可关闭 TTL 清理（例如仅希望依赖明确的 `unsubscribe()`）。

## 运行时 REST 接口

- 查询当前日志配置：
  - `GET /api/logging`
  - 响应示例：
    ```json
    {
      "success": true,
      "data": {
        "level": "info",
        "format": "text",
        "modules": { "transport.webrtc": "debug" },
        "file_path": "logs/va.log",
        "file_max_size_kb": 10240,
        "file_max_files": 5
      }
    }
    ```

- 动态调整日志：
  - `POST /api/logging/set`
  - 请求体字段（可部分提供）：
    ```json
    {
      "level": "debug",
      "format": "json",
      "modules": { "encoder.ffmpeg": "info" },
      "module_levels": "transport.webrtc:trace,analyzer:debug"
    }
    ```
  - 说明：`modules`（对象）与 `module_levels`（字符串）均可使用，后者格式为 `模块:等级,模块:等级`，二者可并存。

- 指标导出运行时开关（非必需）：
  - `GET /api/metrics` 返回：`registry_enabled`、`extended_labels`。
  - `POST /api/metrics/set` 支持动态切换：
    ```json
    { "registry_enabled": true, "extended_labels": false }
    ```

## 环境变量（可选）

- `VA_LOG_FORMAT`: `json` 或 `text`，覆盖 `log_format`。
- `VA_LOG_MODULE_LEVELS`: 形如 `comp:level,comp2:level2`，覆盖模块级别。

## 故障排查建议

- 若日志文件未生成：检查 `observability.file.path` 是否存在父目录或有写权限。
- 若模块级别未生效：确认模块名与代码中的 `VA_LOG_C(level, "module.name")` 一致。
- 若 `/metrics` 出现大量旧源标签：确认 `ttl_seconds` 配置，以及退订/切源路径是否被调用。

