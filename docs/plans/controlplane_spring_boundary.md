## controlplane Spring 重写边界说明

> 目的：为 controlplane 使用 Spring Boot 3.x + Java 21 重写提供清晰的接口契约与范围边界，指导后续实现与测试。

### 1. 接口契约来源

- 设计文档：
  - `docs/design/protocol/控制平面HTTP与gRPC接口说明.md`
  - `docs/design/protocol/控制面错误码与语义.md`
  - `docs/design/subscription_pipeline/lro_subscription_design.md`
  - `docs/design/architecture/controlplane_design.md`
- 现有实现与测试：
  - C++ 代码：`controlplane/include/controlplane/*.hpp`、`controlplane/src/server/*.cpp`
  - Python 脚本：`controlplane/test/scripts/*.py`
  - 其它参考：`docs/plans/controlplane_plan.md`、`docs/plans/controlplane任务分解.md`

后续如调整 API 或增加新接口，应同步更新本文件与上述设计文档。

### 2. HTTP/SSE 接口清单（对外）

#### 2.1 订阅与播放

- `POST /api/subscriptions`
  - 功能：创建订阅，生成 `cp_id` 并触发 VA 订阅 Pipeline。
  - 主要后端：`AnalyzerControl.SubscribePipeline`。
  - 返回：`202 Accepted`，`Location: /api/subscriptions/{cp_id}`，响应体为统一包装的 LRO 资源。
- `GET /api/subscriptions/{id}`
  - 功能：查询订阅状态，支持 `ETag` 与 `If-None-Match`→`304 Not Modified`。
  - 主要后端：CP 内部 Store + VA `GetStatus/QueryRuntime`。
- `DELETE /api/subscriptions/{id}`
  - 功能：取消订阅（幂等）。
  - 主要后端：`AnalyzerControl.UnsubscribePipeline`。
- `GET /api/subscriptions/{id}/events`
  - 功能：订阅阶段事件 SSE 流；测试脚本中存在 `/api/subscriptions/fake-1/events`、`demo-id/events` 等占位用例。
  - 主要后端：`AnalyzerControl.Watch` gRPC 流。
- `GET /whep`
  - 功能：WHEP 媒体出口（含查询参数）；主要由 VA 处理，CP 重写阶段可选择“直通代理”或保持由 VA 暴露。

#### 2.2 源管理

- `GET /api/sources`
  - 功能：聚合所有视频源状态（VSM WatchState / GetHealth）。
  - 主要后端：`SourceControl.WatchState/GetHealth`。
- `POST /api/sources:enable`
  - 功能：启用指定源（例如 `{"attach_id": "...", "enabled": true}`）。
  - 主要后端：`SourceControl.Update`。
- `POST /api/sources:disable`
  - 功能：禁用指定源。
  - 主要后端：`SourceControl.Update`。
- `POST /api/sources:attach`
  - 功能：兼容阶段的 attach 接口（脚本 `check_cp_sources_attach_detach.py` 使用），通过 `attach_id` 与 `source_uri` 建立绑定。
  - 主要后端：`SourceControl.Attach`。
- `POST /api/sources:detach`
  - 功能：解除 attach 绑定。
  - 主要后端：`SourceControl.Detach`。
- `GET /api/sources/watch_sse`
  - 功能：SSE 方式推送源状态（`soak_cp_sse_watch.py` 等用例使用）。
  - 主要后端：`SourceControl.WatchState` 流式转 SSE。

#### 2.3 管线控制与引擎配置

- `POST /api/control/apply_pipeline`
- `POST /api/control/remove_pipeline`
- `POST /api/control/hotswap`
- `POST /api/control/drain`
- `GET  /api/control/pipelines`
- `POST /api/control/set_engine`
- `GET  /api/va/runtime`

上述接口统一封装对 `AnalyzerControl.ApplyPipeline/ApplyPipelines/RemovePipeline/HotSwapModel/Drain/ListPipelines/SetEngine/QueryRuntime` 的调用，具体字段结构以 proto 为准。

#### 2.4 模型仓库与训练相关（可分阶段迁移）

- `/api/repo/*`：包含 load/unload/list/get_config/save_config/put_file/convert* 等模型仓库操作。
- `/api/repo/convert/events`：`convert_upload_cli.py` 使用的转换事件查询接口。

此类接口优先保证只读/轻量操作（如 list/get_config），复杂训练/转换路径可在 Spring 重写后期按需接入。

#### 2.5 观测与调试

- `GET /api/system/info`
  - 功能：聚合 VA / VSM / DB / Trainer 等系统状态，2 秒级缓存。
- `GET /api/_metrics/summary`
  - 功能：CP 层 metrics 汇总视图。
- `GET /api/_debug/db`
  - 功能：数据库连通性与错误快照。

Prometheus 文本格式 `/metrics` 以 VA 为主，Spring 版 CP 使用 Micrometer 暴露 `/actuator/prometheus`，必要时增加代理。

### 3. gRPC 接口清单（CP → VA/VSM）

#### 3.1 AnalyzerControl（VA）

- 服务：`va.v1.AnalyzerControl`（`video-analyzer/proto/analyzer_control.proto`）
- 方法分组：
  - 管线控制：
    - `ApplyPipeline`, `ApplyPipelines`, `RemovePipeline`, `HotSwapModel`, `Drain`, `GetStatus`, `ListPipelines`
  - 订阅数据面：
    - `SubscribePipeline`, `UnsubscribePipeline`, `Watch`
  - 引擎配置与运行时：
    - `SetEngine`, `QueryRuntime`
  - 模型仓库与训练辅助：
    - `RepoLoad`, `RepoUnload`, `RepoPoll`, `RepoList`, `RepoGetConfig`, `RepoSaveConfig`,
      `RepoPutFile`, `RepoConvertUpload`, `RepoConvertStream`, `RepoConvertCancel`, `RepoRemoveModel`

Spring 版 CP 需完整支持上述方法的客户端调用能力，但可按优先级分阶段在 HTTP 层暴露。

#### 3.2 SourceControl（VSM）

- 服务：`vsm.v1.SourceControl`（`video-source-manager/proto/source_control.proto`）
- 方法分组：
  - 源生命周期：`Attach`, `Detach`
  - 健康检查与状态：`GetHealth`, `WatchState`
  - 配置更新：`Update`

SourceControl 是 Spring 版 CP 实现源列表、启停与 SSE 状态推送的关键依赖。

### 4. 兼容性分级与重写优先级

#### 4.1 必须 100% 行为兼容的接口（强兼容）

- `/api/subscriptions`（POST/GET/DELETE）、`/api/subscriptions/{id}/events`（SSE）
- `/api/system/info`
- `/api/sources`、`/api/sources:enable`、`/api/sources:disable`
- `/api/control/apply_pipeline`、`/api/control/remove_pipeline`、`/api/control/hotswap`、`/api/control/drain`、`/api/control/pipelines`、`/api/control/set_engine`
- `/api/orch/*`（health/attach_apply/detach_remove 等，按现有实现保持行为）
- `/api/va/runtime`

上述接口直接影响前端核心功能与现有自动化测试脚本，Spring 重写后需要复用原有错误语义与 JSON 结构。

#### 4.2 建议兼容但允许细节调整的接口

- `/api/sources:attach`、`/api/sources:detach`（更偏向运维脚本与过渡期使用）
- `/api/sources/watch_sse`（可在 Spring 版 CP 中直接使用 SSE 实现，并对心跳/重连策略做小幅改进）
- `/api/_metrics/summary`、`/api/_debug/db`
- `/api/repo/*` 中只读类接口（list/get/poll）

这些接口在语义上应保持一致，但可以在返回字段顺序、非关键字段命名等细节上做适度规范化，只要对现有脚本/前端无破坏。

#### 4.3 可按阶段迁移或暂不支持的接口

- 模型转换与训练相关的重操作接口：
  - `/api/repo/convert/*` 系列（含 events）
  - 其他训练/部署辅助 API（参考训练设计文档）
- 深度调试与内部诊断接口：
  - 临时 `_debug/*` 路由（非文档化但在运维脚本中可能存在）。
- 媒体出口 `/whep`：
  - 初期保持由 VA 直接暴露；Spring CP 可仅作为代理或留空，后续视需要统一。

对上述接口，Spring 版 CP 可以通过“直通代理到 C++ CP/VA”或“暂不暴露”的方式过渡，但需要在发布说明中明确。

### 5. 错误码、返回体与安全约束

- 返回体格式：
  - 成功：`{"success": true, "code": "OK", "data": { ... }}`
  - 失败：`{"success": false, "code": "<ERROR_CODE>", "message": "...", "data"?: {...}}`
- HTTP 状态码与 `code` 对应关系遵循 `控制面错误码与语义.md`：
  - `200/201/204 → OK`；`400 → INVALID_ARG`；`404 → NOT_FOUND`；`409 → ALREADY_EXISTS`；`429/503 → UNAVAILABLE`；`500 → INTERNAL`。
- gRPC 端：
  - 使用标准 `StatusCode`（INVALID_ARGUMENT/NOT_FOUND/ALREADY_EXISTS/UNAVAILABLE/INTERNAL 等），不再依赖额外布尔字段。
- 安全：
  - Spring 重写后，需至少保持与当前 CP 等价的 CORS 白名单与基础鉴权能力，并为后续引入 Token/JWT/mTLS 预留扩展点。

### 6. Spring 重写范围总结

- **纳入本轮重写的核心能力：**
  - 控制平面 HTTP/SSE API（2.1–2.3、2.5）与其背后的 gRPC 调用（3.1–3.2）。
  - 配置加载、错误语义、metrics 与基础安全控制。
- **保留/代理的能力：**
  - 媒体面 `/whep`，可由 VA 暂时继续直出，Spring CP 作为反向代理或路由入口。
  - 高复杂度训练/模型转换相关接口，按阶段迁移。
- **明确不在本轮重写范围内的内容：**
  - VA 内部推理流程、多阶段 Graph 细节。
  - VSM 内部健康探测与源持久化逻辑（仅通过 gRPC 消费其能力）。

本边界说明将作为后续 Phase B–G 任务执行与验收的约束基础。后续如需调整，应通过变更本文件并同步更新相关设计与测试文档。
