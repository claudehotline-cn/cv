# MLflow 模型训练流水线设计（草案）

## 1. 目标与范围
- 引入标准化的训练流水线，统一实验追踪、模型产物管理与上线流程。
- 使用 MLflow Tracking + Model Registry 管理指标与工件；对接现有“模型仓库/加载到 VA”。
- 首期（T0/M0）：分类/检测单卡训练→评估→导出 ONNX→注册→触发 CP 将模型放入仓库并加载到 VA。

## 2. 架构总览
- 角色/服务：
  - MLflow Tracking Server：记录 runs/metrics/params/artifacts；可选 Registry。
  - Control Plane（CP）：训练编排、作业状态（LRO）、触发上线。
  - Model Trainer（新微服务/进程）：执行训练脚本并向 MLflow 上报。
  - Video Analyzer（VA）：在线推理；由 CP 负责将新模型复制/转换并加载。

```mermaid
flowchart LR
  subgraph Web-Front
    UI[训练任务页面]
  end
  UI --> CP[(CP HTTP: /api/train/*)]
  CP -->|start LRO| TRN[Trainer 进程/容器]
  TRN -->|mlflow client| MLF[(MLflow Tracking/Registry)]
  CP -->|SSE events| UI
  CP -->|convert_upload & load| VA[(Video Analyzer)]
  MLF -->|Artifacts/RegisteredModel| CP
```

## 3. 目录与组件划分
- `model-trainer/`（新）：Python 包与可执行脚本
  - `model_trainer/`：训练入口、数据管道、导出与注册适配层
  - `configs/`：Hydra/YAML 配置（数据/模型/训练/导出/注册）
  - `requirements.txt`：pytorch、mlflow、albumentations、pyyaml、hydra-core 等
  - `README.md`：使用说明
- `controlplane/`：新增训练编排接口
  - HTTP：`POST /api/train/start`、`GET /api/train/status?id=...`、`GET /api/train/events?id=...`（SSE）
  - 进程管理：启动/监控 `model-trainer` 子进程；使用 `lro` 记录长任务
- `tools/`：
  - `tools/mlflow/`：运行 Tracking Server 的脚本（Linux/macOS/Windows）
  - `tools/train/`：本地便捷运行与调试脚本

## 4. MLflow 部署与存储
- Backend Store：MySQL（共用宿主 192.168.50.78:13306，库名建议 `mlflow`）
  - 用户：`root`，密码：`123456`
  - 也可先用本地 SQLite（开发期）
- Artifact Store：
  - 默认：本地文件系统 `logs/mlruns`
  - 可选：S3/MinIO（与 ROADMAP 的对象存储计划对齐）
- Tracking Server 启动示例（Linux）：
  - `mlflow server --backend-store-uri mysql+pymysql://root:123456@192.168.50.78:13306/mlflow \
     --default-artifact-root file:/home/chaisen/projects/cv/logs/mlruns --host 0.0.0.0 --port 5500`

## 5. 训练作业生命周期（LRO）
- 状态机：`created → preparing → running → exporting → registering → deploying → done/failed`
- CP 侧：
  - `POST /api/train/start`：接收 YAML/JSON 配置；创建 LRO；启动 `model-trainer` 子进程；返回 `job_id`
  - `GET /api/train/status`：返回阶段、进度、关键指标摘要
  - `GET /api/train/events`：SSE 推送阶段/日志（最小充分）
- 前端：新增“训练任务”页面，展示任务列表、阶段进度、关键指标、跳转到 MLflow UI（可选）

## 6. 配置规范（示例）
```yaml
run:
  experiment: cv-classification
  run_name: resnet50-baseline
  device: cuda:0
  seed: 42

data:
  format: image_folder   # image_folder|coco|yolo
  train_dir: /data/cv/train
  val_dir: /data/cv/val
  num_classes: 10
  aug: weak               # none|weak|strong

model:
  arch: resnet50
  pretrained: true

train:
  epochs: 30
  batch_size: 64
  lr: 0.001
  optimizer: adamw
  scheduler: cosine

export:
  onnx: true
  opset: 17
  dynamic_axes: false
  input_size: [1,3,224,224]

register:
  model_name: cv/resnet50
  tags:
    task: classification
    dataset: myset-v1
  promote: staging         # none|staging|production

deploy:
  via_cp_repo: true        # 触发 CP convert_upload→load VA
  target_repo: default     # CP/VA 的仓库标识
```

## 7. 训练与日志
- 使用 MLflow `mlflow.start_run()` + `mlflow.log_params/metrics/artifacts`；启用 `mlflow.pytorch.autolog()`（可选）。
- 关键指标：`val/accuracy`, `val/mAP`（检测）、`train/loss`, `lr` 等；保存最佳权重与导出 ONNX。
- 日志粒度：每 N 个 step 或每个 epoch；总条目≤必要最小。

## 8. 导出与注册
- 导出：根据配置导出 ONNX（可扩展 TensorRT plan 导出，但推荐复用 CP 的 `convert_upload`）。
- 注册：将最佳 ONNX/ckpt 以 `mlflow.pyfunc` 或专用 flavor（pytorch/onnx）存入 Artifact，并 `mlflow.register_model()`。
- 阶段切换：`staging` 默认；通过 CP/前端“上线”操作推进到 `production`。

## 9. 与 VA 的对接（上线路径）
- 两种路径（二选一或并存）：
  1) 训练流程结束→CP 拉取 MLflow Artifact→调用 `POST /api/repo/convert_upload`→`/api/repo/load`→VA 生效。
  2) 前端在“模型仓库”选择“从 MLflow 注册表导入”，手动挑选版本推进到仓库并加载。
- 路径 1 推荐用于自动化；路径 2 用于灰度与人工验收。

## 10. 接口设计（初稿）
- `POST /api/train/start`
  - 入参：`{ config: YAML|JSON 字符串, sync_deploy?: bool }`
  - 出参：`{ job: string }`
- `GET /api/train/status?id=...`
  - 出参：`{ phase, progress, metrics_summary?, error? }`
- `GET /api/train/events?id=...`（SSE）
  - 事件：`state`（phase, progress, msg?）, `done`（success, best_model_uri?）

## 11. 前端改动点（web-front）
- 新页签“训练任务”：
  - 创建任务（粘贴/上传 YAML），查看状态与关键指标。
  - 任务完成后提供“导入到仓库/上线”快捷动作。
- 组件复用：SSE 事件监听与“柔性推进”进度条逻辑可沿用现有实现。

## 12. 安全与资源
- 资源：GPU/CPU/内存限制由 Trainer 读取配置；后续可对接调度器。
- 隔离：Trainer 作为独立进程或容器运行；避免阻塞 CP 主循环。
- 权限：MLflow 写入凭据单独配置（不复用业务数据库账号）。

## 13. 验收与测试
- 验收（T0）：
  - 能启动训练并在 MLflow 中产生 run、记录指标、保存模型。
  - 能导出 ONNX 并注册；CP 可将其导入仓库并成功加载 VA。
  - 前端能查看训练任务进度（含 SSE 稀疏场景的柔性推进）。
- 测试：
  - 单测：配置解析、数据集采样器、导出函数、MLflow 日志最小闭环。
  - 集成：启动 Tracking Server→跑一个小数据训练（5 epoch）→验证注册与仓库加载。

## 14. 路线图（与现有 M0/M1/M2 对齐）
- T0/M0：单任务训练（分类/检测基础），本地 Artifact，CP 导入仓库并加载 VA。
- T1/M1：对象存储 Artifact（MinIO/S3）、多阶段指标与更稳定的中间进度、检测/分割完备。
- T2/M2：超参搜索（Optuna/MLflow Sweep）、审计与指标上报到 Grafana、回滚/灰度策略完善。

## 15. 未决项
- 训练服务形态：独立微服务 vs. CP 子进程（建议先子进程，后续可独立化）。
- 数据集标准：优先支持 image_folder 与 COCO，YOLO 作为适配层。
- 与现仓库目录结构约定：导入时的标准命名与元数据记录（model.json）。

