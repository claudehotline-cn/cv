# WBS — 基于 MLflow 的模型训练流水线

本文依据《docs/design/training/cv_训练流水线（training_pipeline）详细设计_v_1.md》分解实施工作，按里程碑（M0/M1/M2）与组件（CP/Trainer/前端/MLflow/基础设施）组织。

## 1. 里程碑与范围
- M0 最小闭环：训练→记录→导出→注册→导入仓库→VA 加载（staging）。
- M1 能力扩展：gates 门槛、manifest 完整校验、对象存储、promote/回滚与灰度。
- M2 稳健化：K8s Job 化、资源队列、观测性、安全合规、CI/CD 完善。

## 2. 分解结构（WBS 树）

M0 最小闭环
- M0.1 Control Plane（CP）
  - M0.1.1 训练路由骨架：`/api/train/start|status|events|cancel`
  - M0.1.2 训练执行器：子进程 Runner + stdout JSON 解析 → LRO/SSE
  - M0.1.3 `train_jobs` 表与 CRUD（摘要指标/工件/错误）
  - M0.1.4 manifest 基础校验钩子：集成至 `convert_upload`/`load` 前置（422）
- M0.2 Trainer（Python）
  - M0.2.1 项目骨架 `model-trainer/` + `requirements.txt`
  - M0.2.2 数据模块（image_folder）与最小分类模型（resnet50）
  - M0.2.3 MLflow 记录（params/metrics/artifacts）+ JSON Lines 协议
  - M0.2.4 ONNX 导出 + `model.yaml` + `SHA256SUMS.txt`
- M0.3 MLflow/基础设施
  - M0.3.1 Tracking Server（dev）：MySQL backend + FS artifact（`logs/mlruns`）
  - M0.3.2 最小权限账号与凭据占位（dev 文档化）
- M0.4 前端（web-front）
  - M0.4.1 “训练任务”页（列表/详情）+ SSE 柔性推进复用
  - M0.4.2 `cp.ts` API：`trainStart/trainStatus/trainEventsUrl/trainCancel`
- M0.5 E2E 验收
  - M0.5.1 5-epoch 最小训练→产物与 MLflow 可见
  - M0.5.2 CP 校验 manifest→`convert_upload`→`load`（staging）成功

M1 能力扩展
- M1.1 gates 与评估
  - M1.1.1 任务门槛模板（map/latency/size）
  - M1.1.2 Trainer 输出 gate 结果 → CP 决策
- M1.2 manifest 完整校验
  - M1.2.1 IO/动态轴/兼容矩阵/INT8 校准完整性
- M1.3 对象存储与导入
  - M1.3.1 MinIO/S3 作为 artifact store
  - M1.3.2 CP 拉取与导入仓库路径打通
- M1.4 promote/回滚/灰度
  - M1.4.1 注册表版本晋级（staging→prod）
  - M1.4.2 影子/小流量放量与自动回滚
- M1.5 前端增强
  - M1.5.1 训练对比页与门槛可视化
  - M1.5.2 上线/回滚操作入口

M2 稳健化
- M2.1 执行形态与资源
  - M2.1.1 Trainer K8s Job 化
  - M2.1.2 资源队列/优先级与配额
- M2.2 观测性
  - M2.2.1 CP 任务指标（成功率、时长）与告警
  - M2.2.2 Grafana 面板
- M2.3 安全与合规
  - M2.3.1 TLS/Secret 管理、最小权限账号落地
- M2.4 CI/CD
  - M2.4.1 Trainer 镜像构建与发布
  - M2.4.2 CP 路由回归、端到端烟囱用例

## 3. 交付物清单（关键产物）
- 代码：
  - `controlplane/src/server/{train_routes.*,train_runner.*,manifest.*}`
  - `controlplane/src/server/main.cpp`（注册新路由）
  - `model-trainer/`（Python 包/入口/任务/导出/manifest）
  - `web-front/src/views/TrainJobs.vue`、`web-front/src/api/cp.ts`
- 配置与脚本：
  - `model-trainer/configs/*.yaml`、`requirements.txt`
  - `tools/mlflow/*`（dev 启动脚本）
- 文档：
  - 使用与部署指南、API 约定、manifest 规范

## 4. 依赖与顺序（建议）
1) M0.1（数据层与路由骨架）→ 2) M0.2/M0.3（Trainer 与 MLflow，可并行）→ 3) M0.4（前端）→ 4) M0.5（E2E 验收）。

## 5. M0 验收标准
- 训练任务可发起并追踪（SSE 连续），MLflow 可见 runs/metrics/artifacts。
- 产出 ONNX 与 `model.yaml`，CP 校验通过。
- `convert_upload`→`load` 到 VA（staging）成功，无回归错误。

## 6. 主要风险与缓解
- TRT/ONNX 兼容差异 → CP 增加 trtexec dry-run；必要时回退 ORT CPU 路径。
- 资源争用 → 夜间优先队列、GPU 配额与隔离。
- 凭据与安全 → 最小权限账号、Secret 注入、TLS。
- SSE 稀疏 → 复用“柔性推进”提升可用感。
