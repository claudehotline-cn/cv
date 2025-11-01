# 项目上下文（重生成）— 2025-11-01

本文汇总当前对话与代码现状：体系结构、接口与代理、VA 检测框修复要点、前端编辑器改造、数据库与依赖、测试取证与已知风险，作为研发与联调的统一上下文。

## 1. 组件与端口
- 组件：Controlplane(CP, 18080)、Video Analyzer(VA, REST 8082 / gRPC 50051, TLS)、Video Source Manager(VSM, 7070/7071)、Web 前端(Vite 5173)。
- 连接：前端仅访问 CP；CP 与 VA/VSM 走 gRPC/HTTP；媒体下行经 CP 反代 WHEP。
- 测试源：rtsp://127.0.0.1:8554/camera_01。

## 2. CP：路由与代理（已就绪）
- 新增并稳定三接口（MySQL 读取）：GET /api/models、/api/pipelines、/api/graphs，异常回退与 /api/_debug/db 诊断。
- 订阅：POST /api/subscriptions?use_existing=1&stream_id=...&profile=det_720p&source_uri=rtsp://... → 202 { code:"ACCEPTED", data:{ id } }，并设置 Location。
- WHEP 反代：强制 Accept=application/sdp，处理 Transfer-Encoding: chunked 去分块，重写/透传 Location/ETag/Accept-Patch，CORS 统一，201/204 正确映射。
- Vite 代理：/api,/metrics,/whep → 127.0.0.1:18080，杜绝前端直连 8082。

## 3. VA：检测框修复与配置（进行中→可用）
- 统一 CUDA Stream：Runner→ctx.stream 贯通，预处理/后处理/叠加均在同一 stream，消除跨线程 TLS 竞态导致的框漂移。
- IoBinding dtype 正确性：保持 F16/F32 实型，避免 FP16 被当作 F32 读取；支持设备侧 half_to_float（可选）。
- 归一化坐标还原：按模型输出 normalized 与否，结合 letterbox pre_sx/pre_sy 与 scale/pad 复原几何；CUDA NMS 与 CPU 阈值一致，失败回退 CPU，日志节流。
- 阈值来源：从图配置读取（见 video-analyzer/build-ninja/bin/config/graphs/analyzer_multistage_example.yaml 中 post.yolo.nms: { conf, iou }），不再走环境变量。

## 4. 前端：分析页与管线编辑器（已改造）
- 分析页：统一经 CP 的 /whep 协商与播放；修复预检/CORS/Location 相关提示；强制刷新后无直连 8082。
- 管线编辑器：
  - 画布全屏全宽、右侧抽屉可收起、悬浮竖向分组工具条（预处理/模型/后处理）。
  - 仅允许 out→in 连接；端口高亮与吸附；修复拖拽重复、落点丢失、连线后卡死（禁用原生 drag、DnD 预览/落点克隆、watch 抑制自重建）。
  - 导出 YAML：与示例结构对齐，节点 type 使用 yamlType（preproc.letterbox|model.ort|post.yolo.nms|overlay.cuda），参数内联为字符串。

## 5. 数据库与依赖
- MySQL（cv_cp）：root/123456@127.0.0.1:13306，已有数据。
- 连接器：优先 classic connector（third_party/mysql-connector-c++-9.4.0-winx64），可选 ODBC / MySQL X 作回退。
- 运行库：Windows 下可复用 VA bin 目录中的 mysqlcppconn-10-vs14.dll 等依赖；确保 CP 运行时 DLL 在 PATH。

## 6. 常见问题与修复结论
- 订阅 202 但无播放：多因 Accept/Chunked/Location 或 SSE gating 引起；CP 已修正代理与订阅响应；前端读取 data.id 防止 //events。
- 直连 8082 遗留：已用 Vite 代理与统一 Base 清理，必要时清缓存并强刷。
- WHEP 400/503：先确认 VA REST 8082 在听（netstat），再看 CP 日志 Location/ICE；VSM 空列表时 CP 可合成默认源用于 DEV。
- VA gRPC：需开启并放行端口（TLS），CP/VA 配置一致，必要时用高位端口避免冲突。

## 7. 测试与取证（建议流程）
1) 启动 VSM→VA→CP→前端；
2) 订阅：202 + data.id；
3) WHEP：201（有 Location）→ ICE PATCH 204；
4) <video> loadedmetadata/playing（≤10s）；
5) 算法：boxes>0 且 drawn boxes>0；CPU 与 CUDA 抽样 50 帧 IOU≥0.9；
6) Soak：30 分钟无 5xx；WHEP 不掉线。

## 8. 待办与风险提示
- SSE /api/subscriptions/{id}/events 完整映射 VA Watch（当前部分路径仍占位）。
- 编辑器导出的 YAML 一键下发/应用（CP 接口对接）与阈值可视化调参。
- 生产开关：CP /api/sources 合成回退仅 DEV 打开；发布关闭。
