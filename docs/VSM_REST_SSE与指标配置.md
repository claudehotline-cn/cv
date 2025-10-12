Video Source Manager：REST/SSE 与指标配置

本文件说明 VSM 的 REST/SSE 接口、相关环境变量与 /metrics 指标，并给出常用 PromQL 与 curl 示例，便于接入 Prometheus/Grafana 与联调 VA。

一、REST 接口

服务端口：默认 7071，可通过环境变量 VSM_REST_PORT 覆盖。

- POST /api/source/add
  - 作用：添加并启动一个源会话（Attach）。
  - 参数：支持 query 或 JSON body（Content-Type: application/json）。
    - 必填：id, uri
    - 选填：profile, model_id
  - 返回：{"success":true,"data":{}} 或带 message 的失败说明。

- POST /api/source/update
  - 作用：更新源会话配置（目前支持 profile/model_id）。
  - 参数：id（query 或 JSON）；其余字段同上。

- POST /api/source/delete
  - 作用：删除（Detach）指定源会话。
  - 参数：id（query 或 JSON）。

- GET /api/source/list
  - 作用：列出当前所有会话（attach_id/uri/profile/model_id/fps/phase）。

- GET /api/source/describe?id=...
  - 作用：查询单个会话详情与健康度：fps/jitter_ms/rtt_ms/loss_ratio/last_ok_unixts/phase。

- GET /api/source/health?id=...
  - 等价于 describe（保留别名）。

- GET /api/source/watch
  - 作用：长轮询获取快照，支持阻塞等待。
  - 参数：
    - since 上次收到的修订号（默认 0）
    - timeout_ms 最长等待毫秒（默认 25000）
    - full 1/true 则即使超时也返回完整快照（默认 0）
  - 返回：
    - 有变更：{"rev":new_rev,"items":[...]}（success:true 包装）
    - 超时且 full=0：{"rev":same_rev,"items":[],"keepalive":true}

- GET /api/source/watch_sse
  - 作用：SSE（Server-Sent Events）流式推送变更与心跳。
  - 响应头：Content-Type: text/event-stream, Cache-Control: no-cache, Connection: keep-alive。
  - 参数：
    - since 起始修订号（默认 0）
    - keepalive_ms 心跳与轮询间隔（默认见 VSM_SSE_KEEPALIVE_MS）
    - max_sec 连接最长时长（默认 300），到时主动断开以便客户端重连
  - 事件：
    - 变更：event: update，data: {"rev":...,"items":[...]}
    - 心跳：注释行 “: keepalive”（无数据）
  - 并发：超过限制返回 429 与 JSON 说明（见下文配置）。

二、环境变量与配置

- VSM_REST_PORT（int，默认 7071）：REST 监听端口。
- VSM_METRICS_PORT（int，默认 9101）：/metrics 暴露端口。
- VSM_REGISTRY_PATH（string，默认 vsm_registry.tsv）：注册表持久化路径（TSV：id\turi\tprofile\tmodel_id）。
- VSM_SSE_MAX_CONN（int，默认 16）：SSE 并发连接上限；超出返回 429。
- VSM_SSE_KEEPALIVE_MS（int，默认 15000）：SSE 心跳/等待间隔，可被 watch_sse?keepalive_ms 覆盖。

说明：REST 的 add/update/delete 同时支持 query 与 JSON body，若同名键在两处均出现，服务端以“补齐缺项”为主；建议统一使用 JSON body 传参。

三、/metrics 指标（Prometheus）

暴露端口：默认 9101（VSM_METRICS_PORT）。

- 会话级（按 attach_id 导出）：
  - vsm_stream_up（gauge）1=运行中，0=停止
  - vsm_stream_fps（gauge）帧率估计
  - vsm_stream_jitter_ms（gauge）帧间抖动（1s 窗口估算）
  - vsm_stream_rtt_ms（gauge）占位（未来接入 RTCP/OPTIONS）
  - vsm_stream_loss_ratio（gauge）占位（fps 极低时置 1）
  - vsm_stream_last_ok_unixts（gauge）上次成功时间戳

- SSE 相关（全局）：
  - vsm_sse_connections（gauge）当前 SSE 连接数
  - vsm_sse_rejects_total（counter）SSE 429 拒绝次数累计
  - vsm_sse_max_connections（gauge）配置的上限连接数

常用 PromQL：
- 当前连接数：vsm_sse_connections
- 拒绝速率（近 5 分钟）：rate(vsm_sse_rejects_total[5m])
- 在线会话数：sum(vsm_stream_up)
- 会话 FPS Top5：topk(5, vsm_stream_fps)
- 近 1 分钟内无帧的会话：vsm_stream_fps == 0

四、Grafana 面板建议

- 单值（Stat）：SSE 连接（vsm_sse_connections）、拒绝速率（rate(vsm_sse_rejects_total[5m])）、在线会话数（sum(vsm_stream_up)）。
- 时间序列：SSE 连接与拒绝速率随时间；会话 FPS 折线（可 topk 选取主路）。
- 表格/日志：会话清单（attach_id/uri/fps/phase/last_ok_unixts）。

五、curl 示例

添加会话：
curl -X POST -H "Content-Type: application/json" "http://127.0.0.1:7071/api/source/add" -d '{"id":"camera_01","uri":"rtsp://127.0.0.1:8554/camera_01","profile":"det_720p","model_id":"det:yolo:v12l"}'

更新模型：
curl -X POST -H "Content-Type: application/json" "http://127.0.0.1:7071/api/source/update" -d '{"id":"camera_01","model_id":"det:yolo:v12x"}'

删除会话：
curl -X POST -H "Content-Type: application/json" "http://127.0.0.1:7071/api/source/delete" -d '{"id":"camera_01"}'

REST 长轮询：
curl "http://127.0.0.1:7071/api/source/watch?since=0&timeout_ms=25000"

SSE 订阅：
curl -N "http://127.0.0.1:7071/api/source/watch_sse?since=0&keepalive_ms=10000&max_sec=300"

指标查看：
curl "http://127.0.0.1:9101/metrics"

六、与 VA 的协同（提示）

VA 端可通过 VA_VSM_ADDR 指定 gRPC 地址，并在 app.yaml/环境变量配置 keepalive/backoff/debounce。VSM 的 WatchState（gRPC）或 REST/SSE 事件将触发 VA 侧的自动订阅、切流、切模动作，详见 VA 日志 [ControlPlane] 前缀输出与 /metrics 的 va_cp_auto_* 计数器。

