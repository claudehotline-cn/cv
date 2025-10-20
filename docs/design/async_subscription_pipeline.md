# 异步订阅管线设计方案

## 背景与动机

当前 `/api/subscribe` 同步执行完整的管线构建流程（RTSP 打开、模型加载、Pipeline 启动等），耗时 3–10 秒不等。由于所有逻辑都在处理请求的线程内完成，导致：

- 浏览器使用同一 keep-alive 连接时，其他 HTTP 请求会被阻塞；
- 多个订阅并发触发时会占据大量线程、重复加载模型，容易拖垮 VA 进程；
- 难以观测订阅阶段耗时、失败原因。

目标是将同步流程升级为异步任务模式，让 REST API 快速响应，后台分阶段推进，前端通过轮询或事件获取进度。

## 目标与范围

- REST 接口改造：`POST /api/subscriptions` 返回 `202 Accepted` 和订阅 ID；提供 `GET /api/subscriptions/{id}` 查询状态、`DELETE /api/subscriptions/{id}` 取消任务、可选 `GET /api/subscriptions/{id}/events` SSE。
- 后端实现订阅任务队列，细分阶段：`pending → preparing → opening_rtsp → loading_model → starting_pipeline → ready/failed/cancelled`。
- 订阅任务可限流、可幂等（同一 stream/profile 的并发请求复用已有任务或拒绝）。
- Pipeline 创建成功后更新 TrackManager，并将 pipeline key / WHEP URL 等信息写入状态。
- 将成功/失败事件同步至现有 DB（sessions/logs/events）。
- 前端适配新接口：异步等待 ready 时再发起 WHEP 握手，并在 UI 展示阶段进度。
- 保持向后兼容：设计允许旧接口短期继续存在，待前端升级后移除。

## 系统设计概览

### 新增核心组件

```
RestServer
  ├─ SubscriptionManager（新增）
  │    ├─ 状态表 ConcurrentMap<id, SubState>
  │    ├─ key map ConcurrentMap<baseKey, id>（避免重复）
  │    ├─ 任务队列（ThreadPool + BlockingQueue 或 asio/folly Executor）
  │    ├─ 限流控制（信号量：模型加载、RTSP 连接、总并发）
  │    └─ 事件分发（SSE / Prometheus 指标）
  └─ 现有 Application / TrackManager / PipelineBuilder
```

### 状态数据结构

```cpp
enum class SubPhase {
    Pending, Preparing, OpeningRtsp, LoadingModel, StartingPipeline,
    Ready, Failed, Cancelled
};

struct SubState {
    std::atomic<SubPhase> phase{SubPhase::Pending};
    std::string reason;                // 失败或取消原因
    std::string stream_id;
    std::string profile;
    std::string pipeline_key;          // ready 时可用
    std::string whep_url;              // ready 时生成
    std::string source_uri;
    std::optional<std::string> model_id;
    std::atomic<bool> cancel{false};
    std::chrono::steady_clock::time_point created_at;
};
```

状态由 `SubscriptionManager` 负责维护，对外以 JSON 返回。

### 请求处理流程

1. `POST /api/subscriptions`
   - 校验参数、生成 `subscription_id`，填充 `SubState`，写入状态表；
   - 检查是否存在相同 key (`stream_id:profile`)，如有未完成任务则返回已有 ID（或返回 409）；
   - 将任务封装为匿名函数加入线程池队列，立即返回 `202 Accepted` `{ id, status:"pending" }`。

2. 异步任务执行
   - `phase=Preparing`：记录、装载配置，申请限流信号量；
   - `OpeningRtsp`：调用 `buildSourceConfig` 的逻辑，若失败标记 `Failed`；
   - `LoadingModel`：通过 `resolveModel`、`OrtSession::loadModel` 等流程加载模型，支持取消检查；
   - `StartingPipeline`：调用 `PipelineBuilder::build`、`pipeline->start()`，成功后 `phase=Ready`，保存 `pipeline_key`；
   - 任何阶段抛异常 → 记录 `reason`，phase=Failed，释放限流资源；
   - 如果 `cancel` 被置位：停止 pipeline（若已创建），phase=Cancelled。
   - 成功后写入 SessionRepo / EventRepo / LogRepo，与旧同步流程等价。

3. `GET /api/subscriptions/{id}`
   - 返回 `phase`、`reason`、`created_at`、`pipeline_key`、`whep_url` 等；
   - `ready` 时附带 WHEP URL/ICE 信息（从 Application/SystemInfo 推算）。

4. `DELETE /api/subscriptions/{id}`
   - 将 `cancel` 置位；
   - 如果已有 pipeline key，调用 `app.unsubscribeStream`；
   - 状态转为 `Cancelled`。

5. SSE（可选）
   - 通过 `EventStream` 向前端推送 `{ id, phase, timestamp }`；
   - 控制刷新 UI，而不必轮询。

### 限流与幂等

- 使用 semaphore 限制“重资源阶段”并发量，例如模型加载 `max_model_loading = 2`、RTSP 打开 `max_rtsp_open = 4`，避免瞬间大量任务。
- 以 `stream_id + profile` 作为幂等 key。在状态表中维护 `map<baseKey, sub_id>`：
  - 若已有同 key 的任务且 phase 未终结，直接返回该 ID；
  - phase 为终止态（Ready/Failed/Cancelled）时，允许创建新任务，并更新 map。

### 回收策略

- 订阅任务完成后保留状态（默认 15 分钟），以便前端查阅；之后可定时清理。
- 对于 Ready 状态，应在 `DELETE` 或 App 退出时自动 `unsubscribeStream`，与目前逻辑一致。

### 兼容策略

1. 第一阶段：新增 `/api/subscriptions` 等接口，但保留旧 `/api/subscribe`，继续同步流程；
2. 前端改造完成后，将订阅入口切换到新接口；
3. 观察稳定后，废弃旧接口、旧代码路径，最终只保留异步实现。

## 前端改造要点

- `useAnalysisStore.startAnalysis()` 不再 `await subscribePipeline`，改为：
  1. `POST /api/subscriptions` → 获取 `id`；
  2. 通过 `GET` 或 SSE 轮询状态，更新进度条/提示；
  3. `phase=Ready` 时取出 `pipeline_key` / `whep_url`，再执行 WHEP 握手和统计刷新；
  4. `Failed/Cancelled` 时提示错误，可重试。
- UI 需要展示阶段信息（例如 Loading Model、Starting Pipeline）和取消按钮。
- 释放原有 `unsubscribePipeline` 调用时机，确保取消时同步调用 `DELETE`。

## 数据库与指标调整

- Sessions/Log/Event Repo 写入时机改到 Ready（成功）或 Failed（失败）阶段；
- 增加 Prometheus 指标：订阅总数、各阶段耗时直方图、失败原因统计、排队长度；
- 如需 audit trail，可将状态流转持久化到数据库或日志。

## 风险与缓解

| 风险 | 缓解方案 |
| ---- | -------- |
| 任务执行异常后资源未释放 | 统一使用 RAII / finally 块释放信号量、关闭 pipeline |
| 并发高时，状态表增长无上限 | 定期清理过期任务；可迁移到 Redis 等持久存储 |
| 前端与后端切换不一致 | 通过版本开关逐步发布，保留旧接口直到前端覆盖 |
| 取消处理复杂 | 阶段内检查 `cancel` 标志，重资源操作（模型加载）需在可中断处判断 |

## 里程碑

1. 后端基础：SubscriptionManager、任务队列、状态接口（保持旧接口）；
2. 前端适配：新增订阅流程、阶段 UI、错误处理；
3. 上线 & 灰度：前后端切换、监控指标验证；
4. 清理：移除旧 `/api/subscribe` 同步逻辑。

## 参考

- [docs/plans/async-subscription-rollout.md](../plans/async-subscription-rollout.md) 推进计划
- ONNX Runtime env 共享改动（防止重复初始化）
