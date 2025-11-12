# CONTEXT（2025-11-12）

## 背景
- 前端页面“模型仓库/添加模型”在进行 ONNX→TensorRT 转换时，进度长期停留 5%，完成瞬间跳到 100%，缺少中间进度反馈，影响可用性与感知。
- 新需求：在“模型仓库”中支持“删除模型”（仓库移除模型目录）。

## 变更总览
- 前端（web-front）
  - 改进转换进度显示（“柔性推进”）：在后端事件稀疏时由前端小步推进，运行阶段上限 85%，上传阶段上限 99%；完成至 100%。兼容 progress 为 0–1 或 0–100 两种上报。
  - 事件处理：SSE state/done 事件更新 phase 与 progress；uploading 阶段进度基线≥90%。
  - 修正模板变量：补充 `convertLogs` 占位，避免引用未定义。
  - 新增“删除模型”按钮（列表行与按 ID 操作栏），调用 CP `POST /api/repo/remove`。
- 控制平面（controlplane）
  - 新增路由：`POST /api/repo/remove { model }`，先尝试卸载（best-effort），再通过 gRPC 调用 VA 删除仓库目录。
  - 新增 gRPC 客户端封装：`va_repo_remove_model`。
- Video Analyzer（video-analyzer）
  - Proto 扩展：新增 `RepoRemoveModel` RPC 及消息定义。
  - gRPC 服务实现：`RepoRemoveModel` 在本地 FS 仓库删除 `<repo>/<model>` 目录（S3 删除暂未实现）。

## 关键细节
- 转换阶段（convert_upload）
  - phase：created → running → uploading → done/failed。
  - 控制面 SSE 转发：`/api/repo/convert/events?job=...`，事件 kind=state/done，字段：phase、progress（float）。
- 运行阶段细化（建议，未落地）
  - 可通过解析 trtexec 日志（当前被重定向到 /dev/null）细分 parse/build/tactics/serialize 等子阶段；保持 `phase=running`，仅细化 progress 与可选 detail 字段。
- 删除模型的限制
  - 仅支持本地文件系统仓库路径；S3/MinIO 删除未实现，返回错误提示。
  - 删除前会尝试 `Unload`，避免 in-use 文件，失败不阻塞删除流程（best-effort）。

## API 与路由
- 新增
  - CP HTTP：`POST /api/repo/remove { model }`
  - VA gRPC：`RepoRemoveModel(RepoRemoveModelRequest) returns (RepoRemoveModelReply)`
- 既有
  - `POST /api/repo/convert_upload`
  - `GET  /api/repo/convert/events?job=...`（SSE）
  - `POST /api/repo/(load|unload|poll)`

## 受影响文件（摘录）
- 前端
  - `web-front/src/views/Models.vue`：进度柔性推进、UI 删除按钮与确认、事件处理优化。
  - `web-front/src/api/cp.ts`：新增 `cp.repoRemove(model)`。
- 控制平面
  - `controlplane/src/server/main.cpp`：新增 `/api/repo/remove` 路由。
  - `controlplane/include/controlplane/grpc_clients.hpp`、`controlplane/src/server/grpc_clients.cpp`：`va_repo_remove_model`。
- VA 与 Proto
  - `video-analyzer/proto/analyzer_control.proto`：`RepoRemoveModel` 定义。
  - `video-analyzer/src/controlplane/api/grpc_server.cpp`：`RepoRemoveModel` 实现。
- 备忘
  - `docs/memo/2025-11-12.md`：记录进度优化与删除能力改动与测试建议。

## 构建与运行
- 需全量重建 VA/CP（Proto 变更）。
- 前端在 `web-front` 下 `npm run dev` 运行即可。

## 测试建议
1) 进度显示：上传 .onnx（平台 TensorRT），观察进度 5%→平滑至 ~85%→上传≥90%→100%。
2) SSE 稀疏：仅 start/done 事件情况下，确认前端柔性推进不中断。
3) progress 小数：后端上报 0–1 小数时换算为百分比正确。
4) 删除（FS 仓库）：删除存在模型后，确认列表消失且仓库目录被移除。
5) 删除（S3 仓库）：应提示删除未实现/失败（符合预期限制）。

## 后续工作（建议）
- 细化 running 子阶段（解析 trtexec 输出），提供更稳定的中间进度。
- S3/MinIO 删除实现（ListObjectsV2 + BatchDelete）。
- 弹窗统一使用 Element Plus MessageBox 与更明确的二次确认文案。
- 观测性：记录审计日志与指标（删除、转换、失败率、SSE 连接）。

