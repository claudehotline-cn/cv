# CV 训练流水线（Training Pipeline）详细设计 v1.0

> 本方案面向你当前的 **cv** 仓库（CP/VA/前端/LRO/Repo 管理已存在），增量引入“**模型训练—评估—注册—上线（含灰度/回滚）**”全链路，强调**强约束工件契约（manifest）**、**可观测性**、**安全与凭据**以及**持续迭代**。

---

## 1. 目标 / 非目标

**目标**
- 在不破坏既有 CP↔VA 仓库与推理链路的前提下，引入**训练编排**与**上线门控**。
- 支持 **Detection/Classification/Segmentation** 三任务形态，ONNX/TensorRT 导出，INT8 可选校准。
- 打通 **MLflow Tracking/Registry** 与 **MinIO 模型仓库**（CP 侧落地工件契约校验）。
- 前端新增“训练任务”视图：发起、跟踪、对比、导入仓库、灰度/回滚。
- 形成**可回滚**的生产稳定发布流（promote: staging→prod/rollback）。

**非目标**
- 不在本期引入复杂的 AutoML/超参搜索平台（仅预留接口）。
- 不在本期完成多租户计费/审计（仅预留日志与审计字段）。

---

## 2. 背景与现状梳理

- CP 已实现：`/api/repo/upload`、`/api/repo/convert_upload`、`/api/repo/convert/events`、`/api/repo/load` 等，SSE/LRO 完备。
- VA 已实现：模型加载/热更/仓库集成，缺“导入前强制契约检查”。
- DB：无训练维度表。
- 前端：无 `/api/train/*` 对接页，SSE 能力可复用。

> 关键缺口：训练状态机与 API、工件契约与上线门槛、前端可视化与人机闭环、DB 持久化。

---

## 3. 总体架构

```mermaid
graph TD
  U[Web-Front 训练页] -- REST/SSE --> CP[ControlPlane]
  subgraph CP
    R[Train Routes & Runner]
    M[Manifest 校验]
    D[(MySQL: train_jobs)]
    Repo[Repo 管理]
  end
  R -- 子进程/容器 --> T[Trainer Service (Python)]
  T -- Runs/Artifacts --> ML[MLflow Tracking/Registry]
  ML -- Artifacts --> MinIO[(MinIO Bucket)]
  CP -- 拉取工件/校验 --> MinIO
  CP -- gRPC --> VA[Video Analyzer]
  CP -- Metrics/Logs --> Grafana[Grafana/Prometheus]
```

**形态**：
- Phase-1：Trainer 由 CP 以**子进程**启动（最小闭环）。
- Phase-2：Trainer 封装为 **Docker/K8s Job**（接口保持不变）。

---

## 4. 核心设计决策

### 4.1 状态机（LRO 扩展）

```
created → preparing → running → exporting → validating → packaging → registering → promoting(staging|prod) → done
                                     ↘  failed
```

- **validating**：离线评估（任务指标、延迟/吞吐、体积/显存）。
- **packaging**：生成 `model.yaml` + `SHA256SUMS.txt` + 兼容矩阵。
- **registering**：MLflow 注册/版本化。
- **promoting**：触发 CP → VA 的导入/灰度；失败自动 **rollback**。

### 4.2 工件契约（manifest）

- 引入强约束 `model.yaml`（详见 §8），CP 在 `/repo/load` 前 **强制校验**：
  - IO 签名（名称/shape/动态轴/颜色空间/归一化）。
  - 导出信息（opset/精度/是否动态尺寸）。
  - 兼容矩阵（VA/ORT/TRT 版本）。
  - （可选）INT8 校准工件配套完整。

### 4.3 安全与凭据

- MLflow/MySQL 使用**最小权限账号**（禁用 root），凭据作为 Secret 注入。
- 统一启用 TLS/证书轮换；数据路径只读挂载、导出路径只写。

### 4.4 资源与调度

- 单机优先：DDP（torchrun）/AMP；自动批大小估算。
- 调度：GPU 配额、优先级队列（热修复/灰度 > 正常训练 > 扫参）。
- 健康检查：Trainer liveness/readiness + CP 心跳看门狗。

### 4.5 数据治理（可复现）

- 数据集采用 **版本化标识**（`dataset_name@sha256`），配置中显式写入。
- 推荐：DVC/MinIO remote 或 MLflow Artifacts 存放标注快照；抽样种子固定。

---

## 5. 接口设计（REST + SSE）

### 5.1 启动训练
`POST /api/train/start`
```json
{
  "run": {"experiment": "cv-detection", "run_name": "yolov8s-baseline", "seed": 3407},
  "data": {"format": "coco", "train_dir": "/data/coco/train2017", "val_dir": "/data/coco/val2017", "num_classes": 80},
  "model": {"arch": "yolov8s", "pretrained": true},
  "train": {"epochs": 100, "batch_size": "auto", "lr": 0.01, "optimizer": "sgd"},
  "export": {"onnx": true, "tensorrt": {"enable": true, "precision": "fp16", "int8": {"enable": false}}, "opset": 19, "dynamic_axes": true, "input_size": [1,3,640,640]},
  "gates": {"metrics": {"map50": {"min_delta_vs_baseline": 0.5}, "latency_ms_p95": {"max": 12}}, "artifacts": {"max_size_mb": 200}},
  "register": {"model_name": "cv/detector-yolov8s", "promote": "staging"},
  "deploy": {"via_cp_repo": true, "target_repo": "default"}
}
```
**Response** `202 Accepted`
```json
{"job_id":"t_2025_11_12_001","status_url":"/api/train/status?id=t_2025_11_12_001","events_url":"/api/train/events?id=t_2025_11_12_001"}
```

### 5.2 查询状态
`GET /api/train/status?id=...`
- 返回：`job_id/status/phase/cfg/metrics/artifacts/error/created_at/updated_at`

### 5.3 事件流（SSE）
`GET /api/train/events?id=...`
- `event: phase | metrics | log | gate | artifact | promote | error`
- `data: { ... }`

### 5.4 其它控制面接口
- `POST /api/train/cancel {id}`：优雅终止。
- `POST /api/train/retry {id}`：失败态重试。
- `GET /api/train/logs?id&tail=N`：最近 N 行日志。
- `GET /api/train/artifacts?id`：工件清单与下载 URL。
- `POST /api/train/validate`：对已产出模型做离线复评。
- `POST /api/train/promote {run_id, version, stage}`：注册模型晋级（staging|prod），自动触发导入/灰度。
- `POST /api/train/compare {run_ids:[...]}`：关键指标对比摘要。

### 5.5 与现有 Repo 路由的配合
- `/api/repo/upload` & `/api/repo/convert_upload`：
  - 若存在 `model.yaml`，先解析/缓存；随后所有上传文件完成后整体**契约校验**。
- `/api/repo/load`：前置强校验（失败返回 422/详细原因）。

---

## 6. 组件设计与落点文件

### 6.1 CP（C++）
- **新增** `controlplane/src/server/train_routes.hpp|cpp`
  - 解析请求、调用 Runner、写 DB（train_jobs）、输出 SSE。
- **新增** `controlplane/src/server/train_runner.hpp|cpp`
  - 启 Trainer（Phase-1：子进程；Phase-2：容器/K8s Job）。
  - 读取 stdout/stderr → 解析结构化行（metrics/artifact/gate）。
- **新增** `controlplane/src/server/manifest.hpp|cpp`
  - 解析与校验 `model.yaml`；生成/校验 `SHA256SUMS.txt`。
- **修改** `main.cpp`
  - 注册 `/api/train/*` 路由；在 Repo 路由中引入 manifest 校验钩子。
- **DB 访问** `controlplane/src/server/db.cpp`
  - 增加 train_jobs CRUD。

### 6.2 Trainer（Python）
目录：
```
model-trainer/
  model_trainer/
    entry.py               # 统一入口
    data/datamodule.py     # COCO/YOLO/ImageFolder + Albumentations
    tasks/{classification.py,detection.py,segmentation.py}
    export/{onnx_export.py,trt_export.py}
    eval/{coco_eval.py,gates.py}
    registry/mlflow_adapter.py
    manifest.py            # 生成 model.yaml
  configs/example-det.yaml
  Dockerfile / requirements.txt
```
**stdout 协议**（供 CP 解析）：
- 每条为 JSON Line：`{"type":"metrics","data":{...}}`、`{"type":"artifact","path":"..."}`、`{"type":"gate","pass":true,"summary":{...}}`、`{"type":"error","msg":"..."}`、`{"type":"done","run_id":"..."}`。

### 6.3 VA（C++）
- `Load` 前置：若 CP 标记“已通过契约校验”，直接加载；否则拒绝并回写错误码。
- （可选）回传已加载模型支持的 IO/EP 能力，供 CP 写入兼容矩阵缓存。

### 6.4 前端（Vue3 + TS）
- 新增“训练任务”路由与页面：
  - 列表：状态/阶段/最新指标/开始-更新时间/操作（取消/重试/导出日志/导入仓库/灰度/回滚）。
  - 详情：日志流、指标曲线（loss/mAP/PR）、门槛结果、工件列表。
- `src/api/cp.ts` 新增：`trainStart/trainStatus/trainCancel/trainEventsUrl/...`。

---

## 7. 数据库设计

```sql
CREATE TABLE IF NOT EXISTS `train_jobs` (
  `id`              VARCHAR(64)  NOT NULL,
  `status`          VARCHAR(24)  NOT NULL,
  `phase`           VARCHAR(24)  NULL,
  `cfg`             JSON         NULL,
  `mlflow_run_id`   VARCHAR(64)  NULL,
  `registered_model` VARCHAR(128) NULL,
  `registered_version` INT       NULL,
  `metrics`         JSON         NULL,
  `artifacts`       JSON         NULL,
  `error`           VARCHAR(512) NULL,
  `created_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  CHECK (JSON_VALID(`cfg`)),
  CHECK (JSON_VALID(`metrics`)),
  CHECK (JSON_VALID(`artifacts`))
);
```
> 运行期指标时序数据存入 MLflow；这里保存**摘要**与**关键工件**以便回滚/审计。

---

## 8. 工件契约（`model.yaml`）

```yaml
model:
  name: cv/detector-yolov8
  task: detection                 # classification|detection|segmentation
  framework: pytorch
exports:
  onnx:
    opset: 19
    dtype: fp16                  # fp32|fp16|int8
    dynamic_axes: true
    input_format: NCHW
  tensorrt:
    precision: fp16
    int8:
      enabled: false
io:
  inputs:
    - name: images
      shape: [N,3,640,640]
      normalize: [0.0, 1.0]
      color_space: BGR
  outputs:
    - name: boxes
    - name: scores
    - name: classes
preproc: "resize:letterbox; normalize(0..1)"
postproc: "nms:iou=0.65,score=0.25"
compat:
  va_min_version: 1.6.0
  ort_ep: [CUDA, TensorRT]
  trt_min_version: 10.0
metadata:
  dataset: coco-2017@sha256:xxxx
  trainer_commit: <git-sha>
```

**CP 校验点**：
- `exports.onnx.opset` 与 VA/ORT 版本的兼容表；
- `dtype` 与目标 EP（CUDA/TRT）的支持；
- `inputs.shape` 与 `dynamic_axes`；
- `preproc/postproc` 与 VA 的内置实现是否匹配；
- INT8：如 `enabled:true` 则必须存在校准集与 cache。

**工件目录建议**
```
artifacts/
  checkpoints/best.ckpt
  exports/model.onnx
  exports/model.plan            # 可选
  calibration/cache.json        # 可选 INT8
  samples/val_*.jpg
  reports/metrics.json
  reports/pr_curve.png
  model.yaml
  SHA256SUMS.txt
```

---

## 9. 序列图（训练→上线→灰度/回滚）

```mermaid
sequenceDiagram
  participant FE as Frontend
  participant CP as ControlPlane
  participant TR as Trainer
  participant MF as MLflow
  participant S3 as MinIO
  participant VA as VideoAnalyzer

  FE->>CP: POST /api/train/start(cfg)
  CP->>TR: 启动训练（传 cfg/env/secret）
  TR->>MF: log params/metrics/artifacts
  TR-->>CP: stdout(JSON): metrics/log/artifact/gate
  TR->>CP: 结束回执(run_id, artifacts)
  CP->>S3: 拉取 artifacts
  CP->>CP: manifest 校验 / packaging / SHA256
  CP->>MF: register model / version
  CP->>VA: repo.convert_upload (+onnx) → load (staging)
  VA-->>CP: 成功/失败；指标上报
  CP->>FE: SSE event: promote/staging→prod 或 rollback
```

---

## 10. 评估与上线门槛（Gates）

**任务模板**
- 分类：Top1/Top5、Macro-F1、混淆矩阵。
- 检测：mAP@.5 与 .5:.95、per-class、小目标子集、延迟/吞吐。
- 分割：mIoU/Dice、边界 F-score。

**门槛示例（与 §5 请求体一致）**
```yaml
map50: { min_delta_vs_baseline: 0.5 }   # 相对基线≥0.5pp
latency_ms_p95: { max: 12 }
artifact_size_mb: { max: 200 }
```

**灰度策略**
- **影子**：同流双推理，结果不对外，仅比对指标。
- **小流量**：5%→25%→50%→100% 放量；失败自动回滚上一个 prod。

---

## 11. 安全与凭据

- **数据库**：创建 `mlflow_writer`/`cp_readonly` 等最小权限账号，禁止 root；
- **Secrets**：以文件或 env 注入 CP/Trainer；
- **TLS**：MLflow/MinIO 开启 TLS；证书更新无停机；
- **访问控制**：训练数据路径只读；导出路径只写；Repo 操作启用签名校验。

---

## 12. 监控 / 日志 / 报警

- **Metrics**：训练曲线（MLflow）、CP 任务数/成功率/平均时长、VA 加载失败率、灰度放量指标。
- **Logs**：Trainer stdout/stderr 归档，CP `train_jobs` error 字段记录摘要。
- **Alert**：阶段超时（如 preparing>10min）、promote 失败、加载失败、指标下降超阈。

---

## 13. CI/CD 与环境

- **CI**：
  - C++：单测 + `/api/train/*` 路由回归。
  - Python Trainer：单测（数据模块/导出/manifest 生成），风格检查。
- **镜像**：
  - `cv-trainer:<version>`（torch/cu118+/onnx/tensorrt-cli 可选）。
  - `cp:<version>` 增量编译。
- **环境变量**：`MLFLOW_TRACKING_URI`、`MLFLOW_S3_ENDPOINT_URL`、`AWS_ACCESS_KEY_ID/SECRET`、`DB_*`。

---

## 14. 部署拓扑

- **本地/WSL/Docker**：CP 容器内直接 `fork/exec` Trainer 镜像。
- **K8s**：CP 创建 `Job`，以 ConfigMap/Secret 注入 cfg/凭据；日志走 stdout，事件经 CP SSE 转发。

---

## 15. 迁移计划（里程碑）

- **M1**（最小闭环）：
  - `/api/train/start|status|events|cancel`、`train_jobs` 表、Trainer 子进程、manifest 校验、从 MLflow 导入→VA staging、前端最小页。
- **M2**：
  - promote（staging→prod/rollback）、前端对比页、INT8 校准、灰度影子流。
- **M3**：
  - K8s Job、资源队列/优先级、AutoML/扫参、数据闭环（伪标注/增量采样）。

---

## 16. 关键代码骨架（节选）

### 16.1 CP：`train_routes.cpp`（节选伪码）
```cpp
static lro::Runner g_runner({ .store = lro::make_memory_store() });

Response start_train(Request& req){
  auto cfg = json::parse(req.body);
  std::string job = new_job_id();
  db::create_train_job(job, "created", std::nullopt, cfg);
  g_runner.submit(job, [cfg, job](lro::Operation& op){
    op.phase = "preparing"; notify(op);
    auto p = train::launch_trainer(cfg, job); // 启动子进程
    op.phase = "running"; notify(op);
    while (p.alive()) {
      auto line = p.read_line();
      handle_trainer_line(op, line); // 转换为 SSE 事件/写 DB
    }
    if (!p.ok()) { op.fail(p.error()); return; }
    op.phase = "exporting"; notify(op);
    // 拉取 artifacts/生成 SHA256/manifest 校验
    op.phase = "registering"; notify(op);
    // MLflow 注册 + 版本
    op.phase = "promoting"; notify(op);
    // 调用 repo.convert_upload/load (staging)
    op.done();
  });
  return Response{202, { {"job_id", job}, {"status_url", "/api/train/status?id="+job} }};
}
```

### 16.2 Trainer：`entry.py`（节选伪码）
```python
with mlflow.start_run(run_name=cfg.run.run_name) as run:
  dm = build_datamodule(cfg.data); model = build_model(cfg.model)
  metrics = train_fit_validate(model, dm, cfg.train)
  print(json.dumps({"type":"metrics","data":metrics}))
  onnx_path = export_onnx(model, cfg.export)
  trt_path  = export_trt_if_needed(onnx_path, cfg.export)
  manifest  = build_manifest(cfg, metrics, onnx_path, trt_path)
  mlflow.log_artifact(onnx_path, "exports")
  mlflow.log_dict(manifest, "model.yaml")
  print(json.dumps({"type":"artifact","path":"exports/model.onnx"}))
  print(json.dumps({"type":"gate","pass": gates_check(metrics, cfg.gates)}))
  print(json.dumps({"type":"done","run_id": run.info.run_id}))
```

---

## 17. 风险与对策

- **导出可用性**：不同 opset/动态轴与 TRT 兼容问题 → 在 CP 端 manifest 校验并提供“转换前模拟检查（trtexec dry-run）”。
- **资源抢占**：训练与在线推理争抢 GPU → 队列与配额；夜间时段优先训练。
- **数据漂移**：上线后指标回落 → 保留影子流长期监测；触发再训练并与基线对比。
- **凭据泄露**：root/明文 → Secrets 管理与最小权限。

---

## 18. 附：配置模板（Hydra/YAML）
```yaml
run: { experiment: cv-detection, run_name: yolov8s-baseline, seed: 3407 }

data:
  format: coco
  train_dir: /data/coco/train2017
  val_dir: /data/coco/val2017
  num_classes: 80
  aug: strong

model: { arch: yolov8s, pretrained: true }

train:
  epochs: 100
  batch_size: auto
  lr: 0.01
  optimizer: sgd
  scheduler: cosine

export:
  onnx: true
  tensorrt: { enable: true, precision: fp16, int8: { enable: false, calib_set: /data/calib/1000 } }
  opset: 19
  dynamic_axes: true
  input_size: [1,3,640,640]

gates:
  metrics:
    map50: { min_delta_vs_baseline: 0.5 }
    latency_ms_p95: { max: 12 }
  artifacts:
    max_size_mb: 200

register:
  model_name: cv/detector-yolov8s
  promote: staging

deploy:
  via_cp_repo: true
  target_repo: default
```

---

## 19. 开发任务清单（可直接拆 PR）
- PR-1：`train_jobs` 表 + DB CRUD。
- PR-2：`train_routes.*` + `train_runner.*` + `main.cpp` 注册 + SSE。
- PR-3：`manifest.*` + Repo 路由前置校验（422 细分错误码）。
- PR-4：`model-trainer/` 代码骨干 + 示例配置 + README。
- PR-5：前端“训练任务”页 + API 封装 + 日志/曲线组件。
- PR-6：Promote/灰度/回滚流程（VA 影子订阅 + 放量策略）。
- PR-7：CI/CD（Trainer 镜像、CP 路由单测、端到端 Smell Test）。

---

> 本方案已对齐你现有仓库的组织与风格，保证**最小侵入**与**连续可演进**。若需要，我可以按此文档直接生成 **PR-1 ~ PR-4 的首版代码** 作为起步。

