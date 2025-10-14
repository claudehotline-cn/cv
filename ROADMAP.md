# 路线图总览

覆盖当季第 6–10 周（以下简称“周6–周10”）。本路线图基于 CONTEXT.md 与《docs/references/核心流程修改.md》，以“VSM caps 扩展 + CP 透出”为优先，确保前端除 WHEP 播放外全面对接 Control Plane（CP），并逐步完成可观测、会话语义与性能稳定性目标。

- 里程碑 M0（周6，能力对齐）
  - 名称：能力对齐与端到端贯通
  - 目标：完成“VSM caps 扩展 + CP 透出”的闭环，前端改为仅对接 CP（除 WHEP），上线预检能力与最小可用分析入口。
  - 验收标准：
    - CP：`/api/graphs`、`/api/preflight`、`/api/sources`、`/api/sources/watch` 可用且 sources 含 `caps`；`/api/system/info` 提供 `whep_base`。
    - VSM：`/api/source/list`、`/api/source/describe`、`/api/source/watch` 返回 `width/height/codec/pix_fmt/color_space` 等核心字段。
    - 前端：左侧导航出现“分析”；分析页按 `whep_base` 拼接 WHEP URL；`preflight` 失败时禁用实时分析。

- 里程碑 M1（周8，用户可用）
  - 名称：数据/控制面统一与可观测落地
  - 目标：前端全面切到 CP 数据面与控制面；`watch` 优先 SSE、长轮询兜底；日志与事件基础可观测打通且 UI 可过滤。
  - 验收标准：
    - 前端：`watchSources`/`logsSubscribe`/`eventsSubscribe` 支持 SSE；弱网/代理环境下自动降级长轮询；分析会话 start/stop 的状态与错误提示完整。
    - CP：`/api/logs`、`/api/events/recent` 与 `/api/*/watch` 协议稳定，过滤参数有效；并发客户端下资源占用可控。
    - 测试：源变更→UI 联动、预检门禁、SSE 回退策略的脚本通过。

- 里程碑 M2（周10，性能与稳定）
  - 名称：真实可观测与稳定性硬化
  - 目标：将 logs/events 合成数据替换为真实数据源并固化字段契约；达到当季性能门槛；补全 QUICKSTART 与对齐清单。
  - 验收标准：
    - CP：`logs/events` 输出字段对齐（`ts`、`level/type`、`pipeline`、`node`、`msg`），支持分页/时间窗；可灰度回退合成。
    - 指标：Latency/FPS/GPU 使用率/崩溃率/E2E 成功率达成目标区间（见“指标与验收”）。
    - 文档：核心流程“实际落地与接口对齐清单”与 QUICKSTART 覆盖 Windows 构建与降级策略。

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险缓解 | 指标门槛 |
|---|---|---|---|---|
| P0（周6）对齐与准备 | CONTEXT/ROADMAP 完成，接口清单冻结 | caps 字段统一语义；前端仅对接 CP 的边界及例外（WHEP） | 变更评审与每日站会；接口变更需走变更条 | 接口冻结后不再引入破坏性修改 |
| P1（周6–7）VSM caps 与 CP 透出 | VSM 采集精度确认，CP `/api/sources` 聚合透出 | OpenCV fourcc→codec；BGR/pix_fmt；color_space 默认策略；CP 超时降级 | caps 缺失允许 `preflight` 降级为 ok=true 并提示 | 源列表完整显示分辨率/codec/pix_fmt/color_space |
| P2（周7–8）前端适配与预检联动 | 列表/分析面板显示 caps，`preflight` 护栏生效 | `preflight` 幂等；错误提示与禁用态；WHEP URL 由 CP `whep_base` 拼接 | mock/真实双通道联调；可配置开关 | 预检失败场景提示命中率 100% |
| P3（周8–9）Watch SSE 化 | CP `sources/logs/events` SSE 路由；前端 SSE 客户端 | 心跳/Keep‑Alive；断线重连与节流；多客户端并发 | 长轮询兜底；超时与退避策略统一 | SSE 首屏 <1.5s，重连 <3s |
| P4（周9）logs/events 真实数据源 | 替换合成数据；字段契约稳定 | ts/level/type/pipeline/node/msg 结构；时间窗/分页 | 后端灰度开关；字段校验与兜底渲染 | 事件延迟 P95 < 800ms |
| P5（周9–10）会话与错误处理 | `/api/subscribe` 失败路径清晰，UI 可恢复 | 错误冒泡到前端；避免重复触发；重试退避 | 增加按钮 loading/禁用；一键恢复 | 会话失败可恢复率 > 95% |
| P6（周10）验收与硬化 | 指标评估与文档完善 | Windows LNK1104 规避；ENV 指引；测试脚本覆盖 | 自动化回归 + 手工巡检 | 各项指标达目标区间 |

# 依赖矩阵

- 内部依赖：
  - `video-source-manager`：RTSP 探测与 caps 收集；SSE `/api/source/watch` 推送。
  - `video-analyzer`（CP）：`/api/graphs`、`/api/preflight`、`/api/sources`、`/api/*/watch`、`/api/system/info`。
  - `web-frontend`：导航与分析页、数据提供层统一走 CP、SSE 客户端与回退逻辑。
  - `docs`：核心流程、接口对齐清单、QUICKSTART；变更记录。
  - `tools`：Windows 构建脚本与测试脚本（Stop-Process/环境预检）。

- 外部依赖（库服务硬件）：
  - OpenCV/FFmpeg：fourcc 识别、解码输出 BGR；准确度受限需 UI 明示。
  - yaml-cpp：图 `requires` 解析；异常与容错策略。
  - WebRTC/WHEP：播放出口；iOS 自动播放策略（`muted/playsinline`）。
  - CMake/Ninja/MSVC：Windows 构建链；端口规范（CP 8082、VSM 7071）。
  - RTSP 摄像源或流媒体服务；GPU/驱动（用于推理路径与性能评估）。

# 风险清单（Top-5）

- 描述：caps 准确性不足；触发条件：非常规编码/跨厂摄像头；监控信号：codec 为空/与实际不符；预案：保持 best‑effort，前端标注“估算值”，`preflight` 允许降级放行并提示。
- 描述：SSE 兼容与稳定性；触发条件：代理/弱网限制长连接；监控信号：断线频繁、首屏超时；预案：自动降级长轮询，指数退避重连与心跳保活。
- 描述：Windows 构建失败（LNK1104）；触发条件：可执行被占用；监控信号：链接阶段报错；预案：构建前 Stop-Process，脚本防护与清理临时文件。
- 描述：logs/events 真实数据源不稳定；触发条件：上游波动或结构漂移；监控信号：空窗期/异常率上升；预案：后端灰度开关回退合成，字段校验与兜底渲染。
- 描述：会话失败路径覆盖不足；触发条件：模型/源/引擎异常；监控信号：开始/停止失败率升高；预案：错误冒泡到 UI，限制重复触发，提供“一键恢复”。

# 指标与验收

- Latency：
  - E2E 播放端到端 P95 ≤ 800ms；事件分发 P95 ≤ 800ms；SSE 首屏时间 ≤ 1.5s、重连 ≤ 3s。
- FPS：
  - 1080p 单路稳定 ≥ 25 FPS；多路并发时 P95 ≥ 20 FPS；跌落时 UI 显示降级提示。
- GPU 使用率：
  - 目标区间 40%–70%（满载可上探），一分钟滑窗抖动 ≤ 15%。
- 崩溃率：
  - 后端进程 24h Crash ≤ 0.5%；前端严重脚本错误 ≤ 0.5% 会话；自动重启与上报到位。
- E2E 成功率：
  - 200 次会话样本成功率 ≥ 98%；平均首屏 ≤ 1.5s；失败路径可恢复率 > 95%。
- 验收方式：
  - 使用 `video-analyzer/test/scripts` + 手工巡检记录日志/截图/指标曲线；达标后冻结接口，更新《核心流程修改.md》的“实际落地与接口对齐清单/QUICKSTART”。

