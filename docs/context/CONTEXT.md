# CONTEXT

## 当前进展
- 完成 SubscriptionManager 骨架：状态枚举、并发状态表、任务队列与限流支撑；默认任务路径仍为占位。
- REST 层新增 POST/GET/DELETE /api/subscriptions 路由，返回订阅 ID 与阶段 JSON，并保留同步 /api/subscribe 兼容。
- 构建通过 (	ools/build_va_with_vcvars.cmd)；新源文件纳入 CMake。
- 设计/计划/备忘录文档已更新：docs/design/async_subscription_pipeline.md、docs/plans/async-subscription-rollout.md、docs/memo/2025-10-21.md。

## 待办与约束
- 异步任务仍需接入真实阶段（RTSP 打开、模型加载、Pipeline 启动）并补充失败原因。
- 取消/回滚策略、队列清理及过期状态淘汰尚未实现。
- 需补充 Prometheus 指标与日志，暴露阶段耗时、排队长度、失败率。
- 前端需改造以消费新接口并展示订阅进度。

## 相关决策
- 采用异步任务 + 状态查询 / 可选 SSE 模式，逐步替换同步 /api/subscribe。
- 通过 stream_id:profile 幂等键防止重复构建；引入重资源信号量限制并发。
- 先行提供文档和路线图，后续按阶段落地。

## 风险提示
- 占位实现尚未承载真实工作流，需谨慎对外暴露；维护旧接口作为降级路径。
- 若未同步前端或监控，用户体验与可观测性仍存在缺口。
