# CONTEXT（2025-11-13）

本文件汇总当前对话期间对“训练流水线（training pipeline）”与相关基础设施的架构决策、实现现状与接口清单，作为 M0–M2 里程碑的上下文基线。

## 一、总体架构与目标
- 组件分层：
  - `video-analyzer`（VA，C++/gRPC）：推理、仓库、转换（ONNX→TensorRT plan）与运行时管理。
  - `controlplane`（CP，C++/HTTP）：统一 API 网关与编排层；对外暴露 `/api/*`；通过 gRPC 调 VA，HTTP 反向代理 Trainer。
  - `model-trainer`（Trainer Service，Python/FastAPI）：模型训练/评估与工件产出（ONNX、model.yaml），集成 MLflow 记录指标与工件；支持可选 S3/MinIO 上传。
  - `web-front`：前端 UI，含训练页 `/training`（启动、监控、导入/部署）。
  - 基础设施：MySQL（CP 数据）、MLflow Tracking、MinIO（对象存储，可选）、Redis（后续）。
- 核心目标：将训练职责下沉至独立 Trainer 服务，CP 仅做代理/编排；以 MLflow 记录过程；产出符合仓库规范的 `model.yaml` 与 `model.onnx` 并一键导入部署。

## 二、关键改动（按 PR 结构化）
- PR-1 数据层：新增 `train_jobs` 表与基础 CRUD（CP 内部）。
- PR-2 编排：CP 移除子进程/docker 触发，改为代理外部 Trainer（`trainer.base_url`）。
- PR-3 Manifest 预检：上传/加载前校验 `model.yaml`，422 时返回诊断。
- PR-4 Trainer 骨架：分类训练（ResNet18），MLflow 记录，ONNX 导出与 manifest 生成，SSE 事件（state/metrics/done）。
- PR-5 Infra：Compose 编排 `mysql/mlflow/minio/trainer/cp`；新增 mlflow 预装镜像（避免启动时在线安装）；CP 依赖 `trainer` 就绪；避免 “Unknown database 'mlflow'”。
- PR-6 UI：新增 `/training` 页面（启动、列表、SSE、工件下载、导入并转换→自动加载）。
- PR-7 部署与推广：
  - CP 新增 `POST /api/train/deploy`（门槛 gates：`accuracy_min`、`size_mb_max`），流程：查询状态→拉取 `model.yaml` 校验并保存→下载 ONNX→调用 VA `convert_upload`（返回转换 SSE）。
  - CP 新增别名历史/推广/回滚：`/api/models/aliases (GET/POST)`、`/api/models/aliases/history`、`/api/models/aliases/promote`、`/rollback`。
  - CP 灰度发布最小实现：`/api/deploy/gray/start|status|events`，按 `alias` 解析到 triton 模型，分批对 pipeline/node 调用 `SetEngine + hotswap`。
  - Trainer 工件元数据增强：`/api/train/artifacts` 返回 `size_mb` 与可选 `s3_uri`；支持将工件上传至 MinIO（可选）。

## 三、接口（摘要）
- Trainer Service（FastAPI）
  - `POST /api/train/start`、`GET /api/train/status|list`、`GET /api/train/events?id=...`（SSE）
  - `GET /api/train/artifacts?id=...` → `[ { name, url, size_mb?, s3_uri? } ]`
  - `GET /api/train/artifacts/download?id=...&name=model.onnx|model.yaml`
- Control Plane（HTTP）
  - 训练代理：`/api/train/start|status|list|artifacts|artifacts/download`（代理至 Trainer）
  - 一键部署：`POST /api/train/deploy { job, model, version?, gates? }` → `events`（转换 SSE）
  - 仓库：`/api/repo/upload|convert_upload|convert/events|load|unload|remove|config(GET/POST)`（含 manifest 预检）
  - 别名：`/api/models/aliases(GET/POST)`、`/api/models/aliases/history`、`/promote`、`/rollback`
  - 灰度：`/api/deploy/gray/start|status|events`

## 四、运行与配置
- Compose 关键服务：`mysql`（挂载 `db/schema.sql` 与 `db/mlflow_init.sql`）、`mlflow`（预装镜像）、`minio` + `minio-mc`、`trainer`、`cp`、`va`、`web`。
- 约束与依赖：
  - CP 通过配置 `docker/config/cp/app.yaml` 中 `trainer.base_url: http://trainer:8088` 代理 Trainer。
  - 部署门槛：`deploy.gates.accuracy_min/size_mb_max`（可被请求体覆盖）。
  - Trainer 可选对象存储：通过环境变量 `AWS_*`、`TRAINER_S3_BUCKET/PREFIX` 连接 MinIO。

## 五、验证流程（建议）
1) 训练：前端 `/training` 填写配置 → Start → 观察 SSE 与 metrics → 生成工件。
2) 导入与转换：下载 `model.yaml` 与 `model.onnx`；或在前端“一键导入并转换”，关注 `/api/repo/convert/events`。
3) 一键部署（带门槛）：调用 `POST /api/train/deploy`，返回转换 SSE，完成后自动 `repo/load`。
4) 灰度发布：配置 `canary` 别名 → `POST /api/deploy/gray/start`（指定 pipeline/node 列表、batch、间隔）→ 通过 `/events` 订阅进展 → 成功后 `aliases/promote` 切换 `prod`。

## 六、已知风险与后续
- VA 未运行时灰度计划会在 hotswap 报错（预期）；端到端灰度需 VA 在线。
- `latency_p95_ms_max` 等门槛尚未落地；建议引入评估报告与指标聚合。
- 前端灰度面板与计划管理 UI 待补充（目标：快速选择 pipeline/node 与回滚）。
- 更严格的对象存储路径与鉴权策略待固化（版本化、保留策略）。
