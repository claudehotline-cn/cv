# 路线图总览
- M0「链路打通」：经 CP 实现订阅 + WHEP 协商 + 播放闭环。验收：POST /api/subscriptions 返回 202+Location+data.id；/whep 201（Location 正确重写）、ICE PATCH 204；前端 <video> 正常播放。
- M1「几何正确」：YOLO 检测框在 GPU 零拷贝路径与 CPU 一致。验收：抽样 50 帧 IOU≥0.9；boxes>0 且 drawn boxes>0；阈值来自图配置，切换后重启生效。
- M2「稳定可观测」：长稳运行与问题可诊断。验收：30 分钟 Soak 无 5xx；/_debug/db 能显示数据库异常；WHEP 失败可定位（Accept/Chunked/Location 头取证）。

# 分阶段计划（表格）
| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| P0 | CP WHEP 反代稳定 | Accept=SDP、去分块、Location/ETag 透传、CORS 统一 | VA 未监听/证书问题→端口/证书校验；直连残留→Vite 代理 | 201/204/<video> playing |
| P1 | 订阅接口规范化 | 202 + {data.id} + Location，一致错误码 | 前端读错字段→统一 data.id；SSE 缺失→先解耦 | 订阅成功率≥99% |
| P2 | YOLO 框几何对齐 | 统一 CUDA stream；normalized 还原；CUDA NMS | FP16 读错→dtype 保真；竞态→单一 stream | IOU≥0.9，boxes>0 |
| P3 | 阈值配置贯通 | 图配置读取 conf/iou；编辑器导出 YAML | 环境变量残留→移除；导出格式对齐 | YAML 改动可控生效 |
| P4 | 前端编辑器可用 | 画布全屏；out→in 连线；YAML 导出 | 原生 drag 干扰→禁用/克隆；watch 自重建→抑制 | 连线后可继续操作 |
| P5 | 取证与长稳 | /_debug/db；30min 播放；关键日志节流 | 日志过量→等级开关；VSM 空→合成回退 | 0 掉线/0 5xx |

# 依赖矩阵
- 内部依赖：
  - CP（HTTP/Proxy/DB、WHEP 反代）、VA（REST/WHEP/gRPC、YOLO 后处理、叠加）、VSM（源管理）、Web 前端（Vite 代理、编辑器）。
- 外部依赖（库/服务/硬件）：
  - MySQL（cv_cp）、Mysql Connector/C++/ODBC、CUDA Runtime、ONNX Runtime、FFmpeg/NVDEC、libdatachannel/gRPC、浏览器（WHEP 支持）。

# 风险清单（Top-5）
- WHEP 协商失败 → VA 未监听/证书不匹配 → 201/Location 缺失、ICE 超时 → 校验端口与证书、Accept=SDP、去分块与头透传。
- 框几何偏差 → 归一化还原/阈值/stream 竞态 → boxes=0、框漂移 → 统一 stream、配置化阈值、对齐 NMS 路径并加节流日志。
- 前端直连遗留 → 8082 调用出现 → Network 面板直连记录 → 统一 Base + Vite 代理，强刷清缓存。
- 数据库异常 → 连接器 DLL/权限/驱动 → 三接口为空/超时 → /_debug/db 暴露异常文本，复制依赖 DLL，必要时 ODBC/X 回退。
- 长稳与可观测性不足 → 日志过量/缺少指标 → FPS 下降或排障困难 → 日志等级开关、最小充分取证、保留关键截图/链路清单。
