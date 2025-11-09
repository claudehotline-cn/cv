# Triton In-Process 集成任务清单（Executable Tasks）

仅依据：`docs/references/triton inprocess 集成方案.md`

## P0 Host/会话核心补丁

- [ ] P0-T1 ServerOptions 系统化
  - 动作：设置 BackendDirectory、Pinned/CUDA 内存池、ModelControl=EXPLICIT；注入 backend-config（tensorrt/onnxruntime）。
  - 产出：可运行的 Host 初始化补丁；可通过配置开关参数。
  - 验收：服务启动成功；后端加载正常；日志显示各参数生效。
  - 依赖：无。

- [ ] P0-T2 会话零拷贝与同步
  - 动作：GPU AppendInputData；自定义 ResponseAllocator 实现 size-class 显存池；用 cudaEvent + cudaStreamWaitEvent 替代全局同步。
  - 产出：可用的会话发送逻辑与 Allocator；单测/压测脚本。
  - 验收：零拷贝生效；无全局同步；稳定运行。
  - 依赖：P0-T1。

- [ ] P0-T3 元数据自适配与 Warmup
  - 动作：缓存 ServerModelMetadata；按（batch×shape×profile）执行 Warmup，记录 P50/P90。
  - 产出：元数据缓存模块；Warmup 工具/脚本。
  - 验收：不同模型无硬编码；Warmup 后时延基线可见。
  - 依赖：P0-T2。

## P1 模型仓库控制与别名切换

- [ ] P1-T1 Model Repository 封装
  - 动作：对齐 index/load/unload/poll；生产 EXPLICIT，研发可选 POLL；加载中目录保护。
  - 产出：仓库控制接口与状态管理。
  - 验收：可对单模型执行加载/卸载/轮询；错误可观测。
  - 依赖：P0。

- [ ] P1-T2 别名切换与上线流
  - 动作：实现“上传→Load→Warmup→Alias”流；零中断切换。
  - 产出：上线/回滚脚本与流程文档。
  - 验收：别名切换无中断；异常可回滚。
  - 依赖：P1-T1、P0-T3。

## P2 后端参数标准化（TRT/ORT）

- [ ] P2-T1 TensorRT 后端参数
  - 动作：开放 plugins/coalesce/version-compatible/execution-policy/profile 选择/热身矩阵；映射到 backend-config 或 config.pbtxt。
  - 产出：参数字典与示例配置。
  - 验收：参数可配置并生效；示例模型加载成功。
  - 依赖：P0。

- [ ] P2-T2 ORT + TRT EP 配置
  - 动作：统一 ORT 会话/EP 参数（config.pbtxt 或 backend-config）。
  - 产出：示例 onnx 模型配置。
  - 验收：ORT 路线可启用 TRT EP 并运行。
  - 依赖：P0。

## P3 Ensemble 管线

- [ ] P3-T1 Ensemble 定义与校验
  - 动作：以 ensemble_scheduling 串联预处理→主干→后处理；校验 dtype/shape。
  - 产出：首条 Ensemble 样例与配置。
  - 验收：一次请求贯通；结果正确。
  - 依赖：P2。

## P4 动态批与实例并发

- [ ] P4-T1 动态批/实例组寻优
  - 动作：启用/调优 max_batch_size、preferred_batch_size、max_queue_delay_us 与 instance_group；使用 Perf/Model Analyzer 自动寻优。
  - 产出：推荐配置与画像报告。
  - 验收：达成目标 QPS 与 P90；无明显尾延迟回退。
  - 依赖：P0、P2。

## P5 前端“模型库”与一键发布

- [ ] P5-T1 参数表单与 DAG 编辑
  - 动作：TRT/ORT 参数表单（映射 backend-config/config.pbtxt）；Ensemble DAG 可视化编辑。
  - 产出：UI 表单与 DAG 编辑器。
  - 验收：能配置参数并校验；DAG 成功保存。
  - 依赖：P2、P3。

- [ ] P5-T2 发布与压测集成
  - 动作：实现“上传→Load→Warmup→Alias”一键发布；集成 Perf/Model Analyzer 执行与结果回收；灰度/回滚控件。
  - 产出：发布面板与压测视图。
  - 验收：UI 可完成发布与回滚；压测结果可视化。
  - 依赖：P1、P4。

## P6 缓存与可观测告警

- [ ] P6-T1 响应缓存与指标
  - 动作：开启 response_cache（server+model 维度）；暴露模型状态与错误计数；命中率展示与阈值告警。
  - 产出：指标与告警配置；仪表板。
  - 验收：缓存命中率可观测；异常有告警。
  - 依赖：P0、P1。

## P7 性能验证与验收

- [ ] P7-T1 压测与长稳
  - 动作：Perf Analyzer 并发/速率/数据模式；Model Analyzer 画像；24h 长稳。
  - 产出：压测记录与基线；长稳曲线。
  - 验收：结果达标；无显著爬升；上线/回滚流程可演练。
  - 依赖：P4、P5、P6。

## P8 风险与发布策略

- [ ] P8-T1 风险缓解与脚本化
  - 动作：生产禁用 POLL；TRT plan 与运行时版本校验或 version-compatible 验证；控制 max_queue_delay；评审显存与 CUDA 内存池；Ensemble 一致性校验与必要 cast/reshape；发布与回滚脚本。
  - 产出：风险清单、验证脚本与发布手册。
  - 验收：异常路径演练通过；回滚 100% 成功。
  - 依赖：贯穿 P0–P7。

## P9 文档与示例

- [ ] P9-T1 文档与样例资产
  - 动作：整理 TRT/ORT/Ensemble 样例与 config.pbtxt；参数字典；操作手册。
  - 产出：可复现与运维的完整文档与样例。
  - 验收：新人可按文档完成发布与验证。
  - 依赖：P2、P3、P4、P5。

