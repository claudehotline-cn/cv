# REST API 指南

本文档列出了当前 `video-analyzer` 暴露的 HTTP 接口。旧版 `HTTPServer` 相关的 `/api/analysis/*`、`/api/sources*` 等端点已经废弃，请以此文档为准。

## 模型管理

- `GET /api/models`
  - 返回所有可用检测/分割模型以及加载状态。
- `POST /api/models/load`
  - 请求体：`{"model_id": "det:yolo:v12l"}`。
  - 成功返回 `{ "success": true }`；若加载失败会返回 4xx/5xx 并附带错误信息。

## 订阅/管线

- `POST /api/subscribe`
  - 请求体示例：
    ```json
    {
      "stream": "camera_01",
      "profile": "det_720p",
      "url": "rtsp://127.0.0.1:8554/camera_01"
    }
    ```
  - 可选字段：`model_id`（指定模型）。兼容旧字段名 `stream_id`、`source_uri`。
  - 成功返回 `data.pipeline_key`、`data.subscription_id` 等信息。
- `POST /api/unsubscribe`
  - 请求体：`{"stream": "camera_01", "profile": "det_720p"}`（兼容 `stream_id`）。
- `POST /api/source/switch`
- `POST /api/model/switch`
- `POST /api/task/switch`
- `PATCH /api/model/params`

- `GET /api/pipelines`
  - 返回当前所有活跃管线的状态、FPS、延迟、编码参数、传输统计等。

> 所有 `POST` 端点同时保留无 `/api` 前缀的兼容路径（例如 `/subscribe`）。

## 配置与运行时状态

- `GET /api/profiles`
  - 查看所有 profile 及其默认模型、编码参数。
- `GET /api/system/info`
  - 返回当前应用配置、FFmpeg 状态、模型数量、SFU 地址等。
  - 新增 `engine_runtime` 字段，结构如下：
    ```json
    "engine_runtime": {
      "provider": "cuda",
      "gpu_active": true,
      "io_binding": true,
      "device_binding": true,
      "cpu_fallback": false
    }
    ```
- `GET /api/system/stats`
  - 汇总全局指标：管线数量、累计帧数、丢帧、传输字节数等。
- `POST /api/engine/set`
  - 更新执行引擎（provider、device、IoBinding、TensorRT 选项等）。

## 说明

- 非 JSON 请求将返回 400。
- Server 默认监听 `0.0.0.0:8082`，所有响应均包含 `success` 字段，`false` 时会附带 `message`。
- 若正文较大，请确保客户端正确设置 `Content-Length`，服务端会按长度读取并解析。
