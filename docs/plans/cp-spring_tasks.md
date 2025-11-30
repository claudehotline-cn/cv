按我刚才总结的第「二」和「三」部分，可以整理出这样一份任务清单（从高到低优先级）：

  一、已迁移但行为有差异（需要补齐/对齐）的任务

- 任务 A1：补齐 /api/orch/attach_apply 的 source_id → source_uri 兼容逻辑
  - 内容：在 OrchestratorController.attachApply 中，当只提供 source_id 而无 source_uri 时，按 C++ 行为用 restream.rtsp_base 拼出 RTSP
        URI（注意结尾 / 处理），并保持现有错误码语义不变。
  - 目标：与 C++ CP 在“只传 source_id”场景下行为一致，方便前端/脚本沿用老逻辑。
- 任务 A2：评估并补强 SSE 行为与 C++ CP 一致性
  - 内容：
    - 对比 C++ CP /api/subscriptions/{id}/events 和 /api/sources/watch_sse 的事件序列（phase/state、超时时间、结束条件），审查 Spring
            版目前“最小实现”是否满足所有前端与脚本需求。
    - 若有差异（例如事件数量、超时时长、结束条件不同），在 SseController 中按契约补齐或在文档中明确“裁剪范围”，并补充相应 Web 层测试。
  - 目标：确保现有以及后续新增脚本在 SSE 行为上不因细节差异而产生隐性不兼容。
- 任务 A3：确认是否需要迁移 /api/control/apply_pipelines 批量接口
  - 内容：
    - 检查 C++ 版 /api/control/apply_pipelines 的 JSON 契约和使用方（前端/脚本）。
    - 若仍有实际使用，则在 ControlController 中新增对应端点（复用 ControlService），对齐 C++ 错误码与审计日志。若无使用，则在 ROADMAP/
            设计文档中标记为“暂不迁移，仅保留在 C++ 回退路径”。
  - 目标：避免未来脚本或前端使用批量接口时出现“Spring 版缺少路由”的情况。

  二、仍在 C++ CP 中、尚未迁移到 cp-spring 的任务

- 任务 B1：模型别名与灰度模型接口迁移
  - 内容：在 Spring 中设计并实现 /api/models/aliases 全家桶：
    - GET /api/models/aliases、POST /api/models/aliases
    - DELETE /api/models/aliases/{alias}
    - POST /api/models/aliases/promote、POST /api/models/aliases/rollback
    - GET /api/models/aliases/history...
  - 要求：沿用 C++ CP 的 JSON 结构与错误码 (INVALID_ARGUMENT / NOT_FOUND 等)，并结合 DB schema（若有）完成持久化设计。
  - 目标：让 cp-spring 能接管模型别名/灰度模型管理，为后续灰度发布打基础。
- 任务 B2：灰度发布 /api/deploy/gray/* 及 SSE 迁移
  - 内容：
    - 在 Spring 中实现 POST /api/deploy/gray/start、GET /api/deploy/gray/status 以及 /api/deploy/gray/events SSE。
    - 按 C++ 逻辑管理 rollout 任务状态与事件流（可先以内存实现，后续视需要持久化），保持 JSON 结构与 HTTP 状态码一致。
  - 目标：将“部署灰度”控制面搬到 cp-spring，配合 Phase G 的灰度演练与回滚方案。
- 任务 B3：模型转换相关接口 /api/repo/convert* 迁移
  - 内容：
    - 在 Spring 中实现 POST /api/repo/convert_upload、POST /api/repo/convert/cancel、GET /api/repo/convert/events（SSE）；
    - 封装与 VA 的 RepoConvert RPC 调用，并按 C++ 版的 UNPROCESSABLE_ENTITY、MANIFEST_REQUIRED 等错误细节映射 HTTP/JSON。
  - 目标：支持通过 cp-spring 触发和观察 VA 模型转换任务。
- 任务 B4：训练事件流 /api/train/events 迁移
  - 内容：在 Spring 中增加 SSE 控制器，将 /api/train/events?id=... 代理到 VA 的训练事件流（如存在），保持事件 JSON 结构与 C++ 版一致。
  - 目标：确保训练相关前端/脚本可以无感切换到 cp-spring。
- 任务 B5：通用 SSE /api/events/stream 迁移
  - 内容：在 Spring 中实现 /api/events/stream 的简单 SSE 流（多为前端“占位/心跳”用途），对齐 C++ 实现的事件格式和最小行为。
  - 目标：避免前端在切到 cp-spring 后因为缺少该 SSE 而报错。
- 任务 B6：Agent 代理 /api/agent/threads/{id}/invoke 迁移
  - 内容：
    - 在 Spring 中实现对应的 HTTP → Agent gRPC/HTTP 代理（取决于当前 Agent 接口形式），保持 C++ 中 AGENT_UNAVAILABLE、BACKEND_ERROR 等
            错误语义。
    - 将 Agent 相关配置接入 AppProperties，并加入最小的审计日志。
  - 目标：让前端/脚本可以通过 cp-spring 调用 Agent 能力，为后续 Agent 化场景铺路。
- 任务 B7：调试辅助接口 _debug 系列迁移（可选，优先级低）
  - 内容：视实际使用情况，按需在 Spring 中补充 /api/_debug/echo、/api/_debug/sub/get 等调试路由，或在文档中声明“这些接口仅在 C++ CP 回退
        路径可用”。
  - 目标：避免排障过程中因缺少常用 _debug 接口而降低效率。
