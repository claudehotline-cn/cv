# 项目上下文（最新）

本文件汇总本仓库“视频分析系统”的关键背景、现状、主要变更与风险，覆盖 VA（Video Analyzer）、CP（Controlplane）、VSM（Video Source Manager）、前端与观测链路（Prometheus/Grafana）。

## 1. 组件与目录
- video-analyzer（VA）：RTSP 接入、预处理/推理/后处理、WHEP 输出、/metrics。
- controlplane（CP）：统一 API 与路由；WHEP 代理；DB 访问；SSE（规划中）。
- video-source-manager（VSM）：RTSP 源管理与健康；OpenCV 读取器可选。
- web-front：前端（分析页、Pipelines 编辑器、Observability：Overview/Metrics）。
- docker/compose、docker/va|cp|web|vsm：容器化与编排；docker/monitoring：Prom+Grafana。
- grafana：仪表盘 JSON；docs：context/design/references/memo 等。

## 2. 关键能力与现状
- 分析页“暂停/实时”同会话切换：前端仅调用 `setPipelineMode`；VA 暂停时旁路分析/叠加，恢复时注入一次 IDR，避免花屏与黑帧；不重建订阅/WHEP。
- YOLO 检测修复：统一 CUDA stream；IoBinding dtype 保真（F16/F32）；设备侧解码/NMS 优先（失败回退 CPU）；NV12 叠加内核走同一 stream。
- CP WHEP 代理：统一 CORS/预检；POST 强制 Accept=application/sdp；支持 chunked 去分块；Location 改写；`/api/subscriptions` 返回 `{code:"ACCEPTED",data:{id}}`；VSM 为空时可合成默认源稳定前端（可配置关闭）。
- DB 三接口：`GET /api/models|/api/pipelines|/api/graphs` 由 MySQL 返回（经典/ODBC/X DevAPI 三级兜底）；`/_debug/db` 返回最近 SQL 异常文本。
- 观测：VA `/metrics` 标签转义问题已修复；支持独立 Prom 端点 `observability.metrics.prom_endpoint: 0.0.0.0:9090`；Grafana 可通过 docker/monitoring 或 CP 反代接入前端。

## 3. 前端与编辑器
- 统一走 CP 代理（移除直连 VA）；分析页通过 CP→WHEP 播放；支持 variant=overlay/raw（后台按模式输出）。
- Pipelines 编辑器：画布全屏、左侧分类工具条、连线约束、YAML 导出（对齐 `graphs/analyzer_multistage_example.yaml`）。正修复拖拽复制/释放消失/连线后不可操作等问题，并完善 DAG 合法性校验与属性联动。
- Observability：Overview（Grafana 面板 iframe/PNG 兜底）、Metrics（PromQL 图表与 KPI）。

## 4. 容器化与构建要点
- 新增 VA CPU/GPU、CP、Web、VSM 多阶段 Dockerfile 与 compose；`.dockerignore` 大幅缩小构建上下文。
- Linux/CI 兼容修复：
  - gRPC/Protobuf：优先 CMake CONFIG，失败回退 Protobuf 模块与 pkg‑config(grpc++)；统一探测 protoc 与 grpc_cpp_plugin；替换自定义命令。
  - yaml-cpp：同时支持 `yaml-cpp::yaml-cpp` 与 `yaml-cpp` 目标。
  - jsoncpp：自动探测并在存在时注入 `/usr/include/jsoncpp` 头路径；保留 vcpkg 链接可选。
  - VSM OpenCV 可选：未安装时不编译 RTSP 读取器，提供最小 stub；补齐 <vector> 与 Linux 套接字头。
  - WebRTC/libdatachannel 缺失时：WHEP 媒体改为桩实现（返回 501），保证可编；需要时扩展镜像启用。
  - 编译选项：移除易被错误展开的全局 generator expressions，避免 `-pedantic>` 类问题。

## 5. 数据库与配置
- MySQL：host=127.0.0.1 port=13306 user=root pass=123456 db=cv_cp；VA/CP 统一从配置读取；异常时 `/_debug/db` 诊断。
- Redis：规划中（当前接口未强依赖）。
- 证书/TLS：VA gRPC/HTTP 支持 TLS；CP→VA 走 mTLS（按配置）。

## 6. 仍待推进
- SSE 事件与订阅状态（ready/timeline）映射打通；
- 分析页编辑器交互细节打磨（连线/校验/抽屉属性联动/Apply 闭环）；
- CP 数据源列表的合成兜底加开关并在生产禁用；
- VA 容器默认禁用 WebRTC 发送（无 libdatachannel），如需启用需扩展镜像；
- 长稳（≥30min）播放与 GPU 负载/FPS 回归测试；
- DB 出错返回约定（是否 503）与 CP 故障注入测试。

## 7. 测试与取证建议
- 后端：构建→运行→端口与日志→处理帧数>0；DB 三接口返回非空；
- 前端：订阅 202 → WHEP 201（有 Location）→ ICE PATCH 204 → <video> 播放；切换 pause/resume 不重建会话且首帧 IDR；
- 观测：Prom 目标 UP；Grafana 面板有数据；指标标签无转义错误；
- 文档：每日在 `docs/memo/YYYY-MM-DD.md` 追加任务记录与证据（截图/命令）。

