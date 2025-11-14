# 任务清单 — 基于 MLflow 的模型训练流水线

本文给出可直接映射到 PR 的任务拆分、依赖与验收标准。

## 约定
- 命名：PR-1, PR-2 ...（小步提交，保持 diff 聚焦）。
- 提交信息：祈使句 + 中文（示例：实现 CP 训练路由与 Runner 骨架）。
- 环境：
  - MySQL：`192.168.50.78:13306`，`root/123456`（后续改最小权限账号）
  - MLflow（dev）：FS artifact 根目录 `logs/mlruns`
  - GPU 可选；无 GPU 则以 CPU 路径训练 5-epoch 验收。

## 任务列表（PR 粒度）

PR-1 数据层（train_jobs 表）
- 内容：
  - 新增 `train_jobs` 表（字段见设计 §7），含 `cfg/metrics/artifacts` JSON 字段与索引。
  - C++ DB 访问层 CRUD：`create/update/get/list`。
  - LRO 结构扩展：`phase/progress/summary` 与 `job_id` 映射。
- 验收：
  - 能创建/更新/查询训练记录；JSON 校验通过；与 LRO 状态一致。

PR-2 训练编排（CP 路由与 Runner）
- 内容：
  - 新增 `controlplane/src/server/train_routes.{hpp,cpp}` 与 `train_runner.{hpp,cpp}`。
  - `main.cpp` 注册 `/api/train/start|status|events|cancel`。
  - 子进程 Runner：启动 Python；读取 stdout JSON Lines（type=metrics|artifact|gate|done|error）；转 LRO + SSE。
- 验收：
  - `curl` 能启动训练；`/status` 正确更新；`/events` 连续输出结构化事件。

PR-3 工件契约（manifest 基础）
- 内容：
  - 新增 `manifest.{hpp,cpp}`：解析 `model.yaml`、校验必要字段（task/exports/inputs/outputs/opset/dtype 等）。
  - 在 `/api/repo/convert_upload` 与 `/api/repo/load` 前置校验（失败返回 422，附细分错误码与提示）。
- 验收：
  - 错误 manifest 被拒且返回清晰诊断；正确 manifest 通过并可继续导入。

PR-4 Trainer 骨架（Python）
- 内容：
  - 新增 `model-trainer/`：`entry.py`、`data/datamodule.py`（image_folder）、`tasks/classification.py`（resnet50）。
  - MLflow 集成：记录 params/metrics/artifacts；可选启用 `mlflow.pytorch.autolog()`。
  - 导出：ONNX + 生成 `model.yaml` + `SHA256SUMS.txt`；stdout 打印 JSON Lines（metrics/artifact/done）。
- 验收：
  - 本地 5-epoch 训练成功；产出工件完整；stdout 协议符合；MLflow 存在对应 run。

PR-5 MLflow 基础设施（dev）
- 内容：
  - `tools/mlflow/start_dev.sh|ps1`：以 MySQL backend + FS artifact 启 MLflow Server。
  - 文档化数据库最小权限账号与 Secret 注入约定（留待 staging 落地）。
- 验收：
  - Server 可用；`MLFLOW_TRACKING_URI` 指向后，Trainer 能正常记录。

PR-6 前端训练任务页
- 内容：
  - 新增 `web-front/src/views/TrainJobs.vue` 与列表页；详情展示阶段/指标/工件；复用“柔性推进”。
  - `web-front/src/api/cp.ts` 新增 `trainStart/trainStatus/trainEventsUrl/trainCancel` 包装。
  - 提供“导入到仓库/上线（staging）”快捷动作。
- 验收：
  - E2E 从创建任务到上线闭环在前端可视化；失败态有明确提示。

PR-7 上线扩展（M1）
- 内容：
  - gates：Trainer 输出门槛结果；CP 执行判定（拦截/放行）。
  - promote/回滚：注册表版本晋级（staging→prod）；影子/小流量灰度策略与自动回滚。
  - MinIO/S3 artifact store 接入；导入仓库路径与权限校验。
- 验收：
  - 门槛正确生效；小流量与回滚策略可用；对象存储下导入稳定。

PR-8 稳健化（M2）
- 内容：
  - Trainer K8s Job 化与资源队列/优先级；TLS/Secret 落地；Grafana 面板。
  - CI：Trainer 镜像构建、CP 路由回归、端到端烟囱测试用例。
- 验收：
  - 大规模任务运行稳定；观测性完备；流水线在 CI 中可回归。

## 执行顺序（建议）
PR-1 → PR-2 → PR-4/PR-5（并行） → PR-3 → PR-6 → PR-7 → PR-8。

## 参考
- 设计：`docs/design/training/cv_训练流水线（training_pipeline）详细设计_v_1.md`
- 背景与路线图：`docs/context/CONTEXT.md`、`docs/context/ROADMAP.md`
