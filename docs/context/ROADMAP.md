# 路线图总览

- M0「可播放链路打通」：CP 代理 WHEP 协商稳定，前端可播放。验收：订阅→SSE ready→WHEP 201→ICE PATCH→10s 内 <video> playing，错误率<1%。
- M1「DB 列表与可观测」：/api/models|pipelines|graphs 稳定读库；/api/_debug/db 暴露异常；基础监控与日志齐备。验收：三接口TP99<50ms，异常可定位，前端页面数据非空。
- M2「检测框正确与稳态」：GPU 零拷贝路径下检测框与CPU基线对齐；长稳跑不漂移。验收：50 帧 IOU≥0.95，像素中位误差≤1px；30min 稳定播放无 5xx。

## 分阶段计划（表格）
| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| A | CP WHEP 代理修复 | Accept=application/sdp；chunked 去分块；Location 重写；CORS 统一 | 代理细节不兼容→抓包与最小充分日志 | 播放首开≤10s，201/Location 正确 |
| B | 订阅与 SSE | 返回 data.id；SSE 映射 VA Watch | SSE 断连→退避重连与心跳 | SSE 掉线率<2% |
| C | DB 三接口 | Classic 优先，ODBC/X 兜底；/api/_debug/db | 认证/DLL 缺失→异常快照 | TP99<50ms，非空返回 |
| D | 前端联调 | Vite 代理到 CP；移除直连 VA | 预检失败→统一 CORS 头 | 页面无 CORS 报错 |
| E | 框对齐修复 | 统一 CUDA stream；FP16 处理与核函数参数对齐 | 并行度下降→后续每流水线独立流 | IOU≥0.95 |
| F | 稳定性 & 观察 | 长稳运行观测、压测与报警 | 内存/句柄泄漏→基线巡检 | 30min 无 5xx |

## 依赖矩阵
- 内部依赖：
  - VA（WHEP 端点、推理/后处理、Watch 事件）
  - VSM（RTSP 源清单；为空时 CP 内置开发兜底）
  - 前端（Vite 代理、订阅与 WHEP 调用序）
- 外部依赖（库/服务/硬件）：
  - MySQL 8.x（cv_cp）；ODBC 驱动（可选）；X Plugin（可选）
  - MySQL Connector/C++ 9.4（Classic）运行时 DLL：mysqlcppconn-10-vs14、libssl-3、libcrypto-3
  - GPU 驱动与 CUDA 12.x；ONNX Runtime CUDA EP

## 风险清单（Top-5）
- DB 认证/依赖缺失 → 启用 caching_sha2/RSA/SSL 时 → 三接口返回空 → /api/_debug/db 暴露异常并切换 ODBC/X 或补齐 DLL
- 代理兼容性 → 服务器期望 Accept/编码/Location → 协商 4xx/视频不播 → 强制 Accept=application/sdp、identity；重写 Location 并暴露响应头
- SSE 稳定性 → 网络抖动/代理断流 → 事件缺失/状态不同步 → 心跳+指数退避重连；日志采样与报警
- 框偏移/漂移 → 流不一致/FP16 误读 → 画框错位 → 统一 CUDA stream；确保 dtype 正确；必要时回退 CPU 路径校核
- 并行度退化 → 全局单流串行化 → 多路并发帧率下降 → 稳定后改为“每流水线独立非阻塞流”，保持 ORT user_compute_stream 一致
