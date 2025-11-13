# 路线图总览

- M0「训练与导入打通」
  - 目标：Trainer 服务化（FastAPI+MLflow）、CP 代理 `/api/train/*`、完成“训练→工件→导入并转换→加载”。
  - 验收：前端 `/training` 可启动训练并看到 SSE；产出 `model.onnx/model.yaml`；“导入并转换”成功并能通过 `/api/repo/convert/events` 追踪；VA `repo/load` 成功。
- M1「一键部署与灰度」
  - 目标：`/api/train/deploy`（门槛：`accuracy_min/size_mb_max`）、别名历史/推广/回滚、灰度发布（批次/间隔/事件）。
  - 验收：指标达标即放行；灰度计划能对指定 pipeline/node 分批生效并可订阅事件；推广/回滚在 1 分钟内完成。
- M2「稳健与可观测」
  - 目标：完善门槛（延迟/体积/准确率可配置）、对象存储治理（版本化/保留）、UI/体验完善、指标与审计、自动回滚预案。
  - 验收：Grafana 展示关键指标；回滚演练通过；对象存储清理上线；前端提供灰度计划配置面板。

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
| ---- | ---------- | -------- | --------- | -------- |
| M0 | Trainer 服务 + CP 代理 + 导入转换 | FastAPI/MLflow；CP HTTP 代理；manifest 校验；convert_upload SSE | 组件耦合 → 严格接口、配置旗标 | 训练与导入成功率≥95% |
| M1 | 部署门槛 + 别名 + 灰度 | `/api/train/deploy` gates；aliases promote/rollback；gray start/status/events | VA 不在线 → 探针与失败回退 | 部署达标放行率≥90%；灰度失败可回收 |
| M1.5 | 前端部署/灰度面板 | 训练页操作面板、事件可视化 | 误触操作 → 二次确认/干跑模式 | N/A |
| M2 | 可观测与治理 | 指标/审计；对象存储版本化/保留；回滚剧本 | 采样开销 → 轻量指标与聚合 | 指标采集开销<3% CPU |

# 依赖矩阵

- 内部依赖：
  - CP（HTTP 代理、gRPC 客户端、灰度线程）、VA（convert、hotswap、SetEngine）、Trainer（SSE/工件/MLflow）、Web 前端（训练页、部署按钮、SSE 展示）。
- 外部依赖（库/服务/硬件）：
  - MySQL（CP）、MLflow Tracking、MinIO（可选工件归档）、gRPC/Protobuf、PyTorch、TensorRT/trtexec、GPU（可选）。

# 风险清单（Top-5）

- 训练/部署门槛误判 → 指标口径不一致 → MLflow 字段缺失或命名变更 → 统一指标键（accuracy/val/accuracy），缺省时跳过判定。
- VA 未运行导致灰度失败 → 探针失败/超时 → `/api/deploy/gray/*` 报错 → 启动前检查 VA 健康，失败即终止计划并记录可回收点。
- 对象存储权限或网络异常 → 403/超时 → S3 上传失败事件 → 上传非强制，提供重试/后台补传脚本。
- SSE 稀疏导致体验差 → 训练事件间隔大 → 进度停滞感 → 前端柔性推进与超时提示，落地 metrics 图表。
- 配置漂移/环境差异 → Compose 与运行时不一致 → 启动失败 → 统一 `.env`/模板与健康检查、`depends_on` 顺序。

