# 异步订阅 + SSE 示例

本示例演示如何：
- 创建订阅（POST /api/subscriptions）
- 监听阶段事件（SSE /api/subscriptions/:id/events）
- 就绪后获取 WHEP URL 播放

## 步骤

1) 创建订阅（支持幂等复用）

```bash
curl -s -X POST "http://127.0.0.1:8082/api/subscriptions?use_existing=1" \
  -H "Content-Type: application/json" \
  -d '{
    "stream_id": "camera_01",
    "profile":   "det_720p",
    "source_uri": "rtsp://127.0.0.1:8554/camera_01"
  }'
```

响应示例：`{ "data": { "id": "68f7aa3b1", "phase": "pending" } }`

2) 监听事件（Node/浏览器）

```js
const id = '<上一步返回的 id>'
const es = new EventSource(`http://127.0.0.1:8082/api/subscriptions/${id}/events`)
const phaseToPct = p => ({pending:5,preparing:15,opening_rtsp:35,loading_model:65,starting_pipeline:85,ready:100}[p]||0)

es.addEventListener('phase', ev => {
  try {
    const data = JSON.parse(ev.data||'{}')
    console.log('[phase]', data.phase, phaseToPct(data.phase), '%')
    if (data.phase === 'ready') {
      console.log('[whep]', data.whep_url)
      es.close()
    }
  } catch {}
})

es.addEventListener('error', () => {
  console.warn('sse error, will reconnect...')
  es.close()
})
```

3) 取消订阅

```bash
curl -s -X DELETE "http://127.0.0.1:8082/api/subscriptions/<id>"
```

> 说明：后端已支持 `?use_existing=1` 幂等复用；相同 `stream_id:profile` 已就绪时，直接返回现有订阅 ID。

