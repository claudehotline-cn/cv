高优先级（可直接落地）                                                                           
                                                                                                   
  - 编码器 EAGAIN/丢帧原因精准归属                                                                 
      - 在编码路径（FFmpeg send/receive 处）对 AVERROR(EAGAIN) 进行 per‑source 计数                
    （DropMetrics.encode_eagain），而非仅全局或 zc 计数。                                            
      - 需要将 source_id 注入到编码调用链（建议 Pipeline 在调用 encoder.encode 时传入 track/       
    source_id，或在 Frame 携带 source_id）。                                                         
  - WebRTC 客户端指标                                                                              
      - va_webrtc_clients{state}（connected/completed/failed）                                     
      - va_webrtc_bytes_sent_total{source_id,client_id} / va_webrtc_frames_sent_total{...}         
      - PromQL 面板联动“已连接但 0 吞吐”场景告警。                                                 
  - 自动化校验脚本（轻量）                                                                         
      - PS/Python：订阅→跑流→轮询 /metrics 校验桶单调性、标签齐全性、关键速率阈值；在 CI 或手工回归
    时快速验证。                                                                                     
                                                                                                   

  中优先级（稳定性与可性）                                                                       
                                                                                                   
  - 指标注册抽象与能                                                                             
      - 将手写输出封装为轻量 registry（或引入 prometheus-cpp），避免重复拼接、减少锁粒度。         
      - 对高频路径（队列、编码）尽量使用无锁/原子结构或按源分片锁，降低热点互斥。                  
  - Path 判定与标签完善                                                                            
      - 增加可选标签：decoder（nvdec/ffmpeg）、encoder（nvenc/x264/...）、preproc（cuda/cpu），或合
    成 path_detail（如 nvdec+cuda+nvenc），在现在的 path 基础上可开关式启用。                        
  - 健康检查与就绪探针                                                                             
      - GET /healthz（存活）/GET /readyz（是否有运行中的 pipeline），便于 K8s/监控集成。           
                                                                                                   

  低优先级（生态与可观测体系完善）                                                                 
                                                                                                   
  - Grafana/Prometheus 配置打包                                                                    
      - 提供 docker compose 或 provisioning/ 目录：数据源、面板、告警规则一键导入。                
      - 出一个 alerts.yml：直接可用的告警规则集合（按我们提供的 PromQL）。                         
  - 文档与示例                                                                                     
      - 增补 docs/METRICS.md：指标清单、标签含义、采样建议、常见告警与排障流程；附 Prometheus 抓取 
    示例。                                                                                           
  - GPU/系统资源指标                                                                               
      - va_gpu_mem_usage_bytes、va_gpu_utilization（NVIDIA：NVML）；process_cpu_seconds_total、    
    process_resident_memory_bytes 等，可用于基线与容量预估。                                         
                                                                                                   

  实现建议与拆分点                                                                                 
                                                                                                   
  - 为编码器补充 source_id 贯通                                                                    
      - 方案 A：在 va::core::Frame 中新增 const char* source_id 或 std::string_view，Pipeline 设置 
    后下游可读；不影响数据拷贝。                                                                     
      - 方案 B：扩展 IEncoder::encode(const Frame&, const Context& ctx, Packet&)，Context 携带     
    source_id/track_id。                                                                             
  - 并发与锁                                                                                       
      - 当前 DropMetrics/SourceReconnects/NvdecEvents 使用 std::mutex 保护 map，吞吐为主场景建议做 
    按源分片或使用 concurrent_unordered_map（必要时）。                                              
  - 监控开关                                                                                       
      - 为新增指标增加可控开关（配置或环境变量），在极端低延迟场景可关闭高频事件统计。 



规划已就绪，我先开启“Registry 方案设计”，其余步骤按序推进。

  方案概述

  - MetricsRegistry 目标
      - 统一 Counter/Gauge/Histogram 增量接口，隐藏文本拼接细节
      - 降低锁粒度：按 source 分片 + 原子计数，避免全局互斥热区
      - 兼容现有输出格式与命名，不破坏现有仪表盘/告警
  - 并发与存储
      - 每个 source_id 对应一个结构体，内部成员为 std::atomic 计数（processed/dropped/encoder/回压/
    重连/NVDEC 等）
      - 全局采用固定 N 分片（如 16）哈希桶，注册/获引用时持分片锁，读写计数用原子操作
      - Histogram 仍由 Pipeline 内部维护（已是原子快照）；Registry 只聚合并序列化
  - 标签与兼容
      - 默认保留现有 labels：source_id、path
      - 新增可选 labels（默认关闭，避免基数暴涨）：
          - decoder：nvdec/ffmpeg
          - encoder：解析 encoder.codec（nvenc/x264/…）
          - preproc：cuda/cpu（基于现有开关或运行态信号）
      - 配置开关：observability.metrics.extended_labels = false（默认）；开启后才输出上述额外标签  
  - 导出与替换策略
      - /metrics 导出改为遍历 Registry 快照输出（文本 0.0.4）
      - 逐步迁移：DropMetrics/SourceReconnects/NvdecEvents 的内部存储替换为 Registry 节点或桥接适  
    配器
      - 保留现有指标名，不新增重复序列（仅扩展 labels）
  - 验收与验证
      - 性能：在 60 fps × N 源场景下，增量操作锁争用近零（仅注册/新增源持锁）
      - 兼容：不开启扩展标签时，现有仪表盘与告警无需改动
      - 正确性：直方图桶单调性、sum/count 一致性；各计数与现有值一致



不改变主流程和对外接口，影响可控，默认无感知。
                                                                                                   
  具体影响与边界                                                                                   
                                                                                                   
  - 对外接口                                                                                       
      - 路由与文本格式：GET /metrics 保持 Prometheus 0.0.4 文本格式，不新增必选路由或格式变化。    
      - 指标名：沿用现有指标名（pipeline_fps、frames_dropped_total…）。新增的 decoder/encoder/     
    preproc 标签为可选，默认关闭，兼容现有看板与告警。                                               
  - 内部架构                                                                                       
      - 新增组件：轻量 MetricsRegistry（全局单例），负责计数存储与/metrics 序列化，不影响数据平面  
    （拉流、分析、编码、传输）。                                                                     
      - 线程模型：采用“按 source 分片 + 原子计数”的无锁增量（仅注册/新增源短暂持分片锁），替代现有 
    多个 map+mutex 的热点互斥。                                                                      
      - 迁移方式：逐步把 DropMetrics/SourceReconnects/NvdecEvents 的内部存储接入 Registry 或通过适 
    配层桥接；Pipeline 的直方图仍由 Pipeline 维护，导出时 Registry 汇总并输出。                      
      - Path 判定：沿用现有启发式（d2d > gpu(nvenc) > cpu）；可选扩展标签 decoder/encoder/preproc  
    的判定逻辑在导出阶段附加，默认关闭不影响现状。                                                   
  - 触达范围                                                                                       
      - 受改文件：server/rest.cpp（/metrics 输出改为从 Registry 快照）、新增 core/                 
    metrics_registry.*、若干原 metrics 模块适配（不改变 Pipeline/Analyzer/Encoder/Transport 的调用   
    签名）。                                                                                         
      - 不改动：订阅/切源/编码/传输等业务流程代码路径与接口签名。                                  
  - 配置与回滚                                                                                     
      - 新增开关：observability.metrics.extended_labels（默认 false）；                            
    observability.metrics.registry_enabled（默认 true，可快速回退到旧路径）。                        
      - 回滚策略：保留原有导出代码路径开关可切，合入后问题可一键回退。                             
  - 风险与缓解                                                                                     
      - 标签基数膨胀：扩展标签默认关闭；开启需在配置明确 opt-in。                                  
      - 内存占用：Registry 按 source 分片存储，节点回收与 idle reaper 与 TrackManager 生命周期对   
    齐；提供最大源条目与过期淘汰保护。                                                               
      - 并发正确性：增量使用原子，快照采用分片读锁+原子读，保证一致性与低抖动。                    
  - 预期收益                                                                                       
      - 高并发下 /metrics 生成开销下降，锁争用显著减少。                                           
      - 统一的注册/导出抽象，后续接入 prometheus-cpp 或 OTEL 更顺滑。