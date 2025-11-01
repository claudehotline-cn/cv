# 路线图总览

- M0 基线打通（CP↔VA 播放 + 监控 + DB）
  - 目标：前端经 CP 完成订阅与 WHEP 播放；Prom/Grafana 可用；/api/models|/pipelines|/graphs 返回数据库数据。
  - 验收：订阅202→WHEP201（有 Location）→ICE PATCH204→<video> 播放；Prom 目标 UP；Grafana 仪表盘展示关键指标；DB 三接口非空或清晰错误说明。
- M1 稳定与性能（检测框正确 + 同会话切换 + 长稳）
  - 目标：GPU 零拷贝路径几何一致；pause/resume 同会话无黑屏；30min soak 无 5xx、FPS 稳定。
  - 验收：CPU/GPU 几何 IOU≥0.95；切换注入 IDR 可见；30min 播放不中断，错误率阈值内。
- M2 生产化（容器化 + 安全 + 运维）
  - 目标：一键 compose（VA/CP/Web/VSM/监控）；TLS/mTLS 生效；编辑器 YAML Apply 闭环；自动化回归。
  - 验收：灰度部署通过；管控/观测基线 OK；变更有回滚方案与文档。

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| P0 | 播放基线 | CP 代理 WHEP；Accept=SDP；Location 改写；chunked 去分块 | VA 未起/端口不通→健康探针与日志；代理容错 | <10s 首帧；错误率<1% |
| P1 | DB 三接口 | MySQL 经典/ODBC/X DevAPI 兜底；/_debug/db | 认证/依赖缺失→兜底与可观测；超时控制 | 查询<50ms；异常清晰 |
| P2 | 观测接入 | Prom 9090/8082；Grafana 面板/iframe | 标签转义/跨域→统一规范与反代 | 面板全绿；关键指标齐 |
| P3 | 框与性能 | 统一 CUDA stream；IoBinding dtype；设备侧解码/NMS | 几何偏差→回退 CPU；单测对齐 | IOU≥0.95；FPS 不回退 |
| P4 | 同会话切换 | setPipelineMode 注入 IDR；不重建 WHEP | 花屏→强制 IDR；竞态→节流 | 切换<1s；零重连 |
| P5 | 编辑器闭环 | 画布/连线/校验；YAML 导入/导出/Apply | 交互冲突→约束与提示 | 导出=示例 YAML |
| P6 | 容器化上线 | VA/CP/Web/VSM 镜像；compose；监控栈 | 构建依赖分歧→兜底与缓存 | 一键 up；健康通过 |

# 依赖矩阵

- 内部依赖：
  - VA（推理/叠加/WHEP/metrics）、CP（代理/DB/SSE）、VSM（源健康/可选读取器）、web-front（分析页/编辑器/观测）。
  - lro（可选运行库/头）。
- 外部依赖（库/服务/硬件）：
  - MySQL 8.x、（可选）Redis；Prometheus/Grafana；ONNX Runtime；FFmpeg；OpenCV（VSM 可选）；gRPC/Protobuf；yaml-cpp/jsoncpp；libdatachannel（可选）；CUDA/NVIDIA 驱动与 NCT（GPU）。

# 风险清单（Top-5）

- WHEP 端到端不稳 → VA 未监听/代理头不兼容 → 网络 4xx/5xx、Location 缺失 → 健康探针 + 代理容错 + 最小重试。
- 几何不一致/框漂移 → 流水线多 stream/TLS 竞态 → 画面与日志偏差 → 统一 CUDA stream + 回退 CPU + 单测对齐。
- DB 依赖缺失或认证失败 → 连接错误/空数据 → /_debug/db 有异常文本 → 多驱动兜底 + 明确错误码。
- 观测不可用 → 标签转义/CORS/端口错配 → 面板空白/target DOWN → 统一格式 + 反代 + 启动检查清单。
- 容器构建分歧 → 发行版包/目标名差异 → CMake 找不到包 → CONFIG→Module/pkg-config 兜底 + .dockerignore 减载 + 分阶段启用。

