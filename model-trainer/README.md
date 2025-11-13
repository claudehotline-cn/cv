## Model Trainer (MLflow Skeleton)

本目录提供最小可运行的训练器骨架，用于实现 PR-4：
- 训练（分类任务示例，CPU 可运行）
- 指标与工件上报（MLflow，可通过 `MLFLOW_TRACKING_URI` 配置）
- 导出 ONNX（`artifacts/exports/model.onnx`）
- 生成 `artifacts/model.yaml`（满足最小 manifest 校验）
- stdout 输出 JSON Lines（type=metrics|artifact|done）供 CP 解析

### 运行（示例）

- 方式 1：最小运行（随机数据，CPU）
```
python -m model_trainer.entry -c model-trainer/configs/example-cls.yaml
```

- 方式 2：指定本地数据（ImageFolder 结构）
```
python -m model_trainer.entry -c model-trainer/configs/example-cls.yaml \
  data.train_dir=/path/to/train data.val_dir=/path/to/val data.num_classes=10
```

说明：
- 若未设置 `MLFLOW_TRACKING_URI`，将默认写入项目内 `logs/mlruns`（文件存储）。
- 主要输出在 `artifacts/` 目录下；stdout 将打印关键 JSON 事件。

### 依赖

请先安装：
```
pip install -r model-trainer/requirements.txt
```

建议在独立 venv 或容器内使用。

### 配置模板
参考 `model-trainer/configs/example-cls.yaml`，可通过 CLI 形如 `key=value` 的覆盖修改任何字段。

### Docker 镜像（同仓库独立项目）

- 构建镜像：
```
docker build -f docker/trainer/Dockerfile -t cv/trainer:latest .
```

- 运行（读取挂载的配置）：
```
docker run --rm \
  -e MLFLOW_TRACKING_URI=http://localhost:5500 \
  -v "$PWD/model-trainer/configs":/config:ro \
  cv/trainer:latest -c /config/example-cls.yaml
```

- 与 CP 对接（可选）：将 CP_TRAINER_CMD 指向该镜像（需要按环境准备共享卷/路径）：
```
CP_TRAINER_CMD="docker run --rm -e MLFLOW_TRACKING_URI=http://mlflow:5500 cv/trainer:latest -c {config}"
```
说明：若以 docker 方式运行，需确保 `{config}` 文件对 docker 宿主可见（建议放置在共享卷目录）。

### 通过 MLflow Projects 启动（不新建容器）

- 在已安装依赖的环境中（或 cp 容器中）：
```
mlflow run model-trainer -P config=model-trainer/configs/example-cls.yaml --env-manager local
```

- 配合 CP（替换 CP_TRAINER_CMD）：
```
CP_TRAINER_CMD="mlflow run /app/model-trainer -P config={config} --env-manager local"
```
说明：
- MLflow Tracking Server 不负责拉起训练作业；`mlflow run` 是本地/后端执行入口，需要在可执行环境内运行。
- `--env-manager local` 表示复用当前环境（需预先安装依赖）。
