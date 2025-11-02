# 取消用例的 SSE 轨迹验证（Playwright MCP｜最小取证）

目标：以最小取证方式验证异步订阅的 SSE 可用，且取消请求返回 202（status=cancelled）。

- 前置条件：
  - VideoAnalyzer 已在本机运行，默认地址 `http://127.0.0.1:8082`。
  - 如命中配额限流，可将运行时配置 `app.yaml` 的 `quotas.observe_only=true` 或提高 `default.rate_per_min`（本仓库 smoke 环境已默认放宽）。

- 工具与约束（Playwright MCP）：
  - 仅使用：`browser_navigate`、`browser_evaluate`（不截全页、不做 DOM dump）。
  - `browser_evaluate` 仅返回结构化 JSON（≤10 个关键字段）。

## 步骤（MCP 指令）

1) 打开空白页
- `browser_navigate` → `about:blank`

2) 执行最小取证脚本（仅一次 `browser_evaluate`）
- 逻辑：
  - POST `/api/subscriptions` 创建订阅（示例 RTSP：`rtsp://127.0.0.1:8554/camera_01`）。
  - 连接 SSE：`/api/subscriptions/{id}/events`，捕获首个 `phase` 事件名（用于佐证 SSE 正常）。
  - 发送 `DELETE /api/subscriptions/{id}` 并读取返回。
  - 返回 JSON：`{ id, firstPhase, delete: { code, status } }`。

- 建议代码（传入 `browser_evaluate.function`）：

```js
async () => {
  const base = 'http://127.0.0.1:8082';
  const payload = { stream_id: 'mcp_cancel_demo', profile: 'det_720p', url: 'rtsp://127.0.0.1:8554/camera_01' };
  const r = await fetch(base + '/api/subscriptions', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
  const jr = await r.json().catch(()=>({}));
  const id = jr?.data?.id || '';
  if (!id) return { error: 'no-id', status: r.status };
  let firstPhase = null;
  await new Promise((resolve) => {
    let es; try { es = new EventSource(base + '/api/subscriptions/' + encodeURIComponent(id) + '/events'); } catch { resolve(); return; }
    const t = setTimeout(() => { try{es.close()}catch{}; resolve(); }, 2000);
    es.addEventListener('phase', (ev) => { try { const d = JSON.parse(ev.data||'{}'); if (!firstPhase) firstPhase = (d.phase||null); } catch {} });
    es.onerror = () => { try{es.close()}catch{}; resolve(); };
  });
  const del = await fetch(base + '/api/subscriptions/' + encodeURIComponent(id), { method:'DELETE' });
  const code = del.status; const dj = await del.json().catch(()=>({}));
  return { id, firstPhase, delete: { code, status: dj?.data?.status || null } };
}
```

## 通过标准
- 取消成功：`delete.code === 202` 且 `delete.status === 'cancelled'`。
- SSE 证据：`firstPhase` 为非空字符串（如 `pending`/`ready`/`opening_rtsp` 等，具体值与时序相关）。

## 备注
- 本用例不截图、不导出日志；仅保留必要的结构化 JSON。
- 如需进一步钻取，可在后续步骤使用 `GET /api/subscriptions/{id}?include=timeline` 读取时间线，但默认不返回以控制取证体量。
