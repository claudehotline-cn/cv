# LRO 集成与迁移指南（VA）

本文面向 VA，将订阅类任务迁移到通用 LRO 编译库（lro_runtime）的完整接入步骤与注意事项沉淀如下。

## 目标与原则
- 保持对外语义不变：POST 202+Location、GET ETag/304、SSE 事件、JSON 字段名。
- LRO 完全通用：库内不出现 VA 专有常量（phase/reason 等），状态与统计经由通用 `states`/快照输出。
- 渐进迁移可回滚：独立编译库，必要时移除链接与路由切换即可回退。

## 组件与接口
- Runner：创建/查询/取消/观察（create/get/cancel/watch），支持 Steps（IO/Heavy/Start）。
- StateStore：内置 `MemoryStore`，SPI 可替换（Redis/DB/WAL）。
- Notifier：SPI（Callback/自定义），对接 SSE/WS/Webhook/MQ。
- AdmissionPolicy：并发/队列/重试估算 SPI，VA 侧用于 429 Retry-After 与 /metrics。

## 接入步骤（VA）
1) 引入库
   - 首选：`add_subdirectory(../lro ... EXCLUDE_FROM_ALL)`，`target_link_libraries(VideoAnalyzer PRIVATE lro_runtime)`。
   - 或安装后 `find_package(lro)`，链接 `lro::lro_runtime`（保留头路径）。
2) REST 切换
   - `rest_subscriptions.cpp`：POST/GET/DELETE/SSE 改走 Runner。POST 返回 202+Location；GET 支持弱 ETag；SSE 发送 phase 事件。
   - 失败/取消 reason 在 VA 层归一（不写入库内）。
3) 指标与系统信息
   - `/metrics`：输出 queue_length、in_progress、states{phase}、completed_total、duration 直方图；镜像 WAL 指标；SSE/Codec/Quota 维持现状。
   - `/system/info`：`subscriptions` 回显 slots/queue/in_progress/states 与来源（config/env）。
4) Admission/Retry-After
   - 429 对 global/key 并发、key 速率、queue_full 路径使用 Admission 估算重试时间（上限 60s）。
5) WAL：在 POST/终态（GET 命中或 DELETE）落证，去重一次。
6) 清理与回滚
   - 删除 SubscriptionManager 源与引用；如需回滚，仅恢复路由与链接配置。

## 验证清单
- 最小 API：POST→GET→DELETE+SSE；idempotency 重发命中。
- 失败路径：ACL 拒绝、模型加载失败、订阅失败；取消中断。
- 指标：`va_subscriptions_*` 基础与直方图存在；WAL/预热/缓存/Quota/SSE/Codec 指标齐全；
- E2E 脚本：运行 `tools/run_ci_smoke.ps1` 全绿。

## 构建与安装
- 库提供 `install/export` 与 `lroConfig.cmake`；可作为独立仓库发布，或子目录引入。
- Windows 构建注意停进程再链接（避免 LNK1104）。

## 风险与建议
- 指标基数膨胀：限制 states/reason 标签集合，必要时聚合。
- RTSP/网络抖动：Soak 指标容错并分类错误类型；适度延长超时与重试退避。
- WAL 旋转/TTL：tail 取样仅作近实时参考，审计类场景走离线统计。

