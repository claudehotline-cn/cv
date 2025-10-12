Stage 7 原计划包含的工作里，尚未完成的主要有几类：
                                                                                      
  1. 真正的 GPU/IOBinding 管线落地                                                    
      - 虽然现在能上报 device_binding，实际上并未把推理输出绑定到 GPU 缓冲后再被后续环节消费。                                                                            
      - 需要沿着 Pipeline → Analyzer → Renderer/Encoder 把 GPU Tensor 传递、转换并避免额外的 host 拷贝，才能算真正完成「IOBinding 支持」。                                
  2. WHIP/WHEP 相关扩展                                                               
      - 目前 transport_whip.* 仍是占位实现，没有真正的 WHIP/WHEP 传输栈。             
      - Stage 7 要求评估并封装成熟方案或对接第三方服务，这部分还未开始。              
  3. 自动化/压力测试                                                                  
      - GPU 切换、TensorRT 运行、模型切换等只做了脚本层面校验，没有持续集成或压力回归 
  （长时间推流、模型热切换）来验证稳定性。                                            
  4. 前端联动                                                                         
      - 虽然后端 REST 已返回 engine_runtime，前端还未使用这些字段（模式提示、告警、切 
  换操作等功能尚未落地）。                                                            
  5. 性能与回退监控                                                                   
      - Stage 7 期望在日志/指标里统一记录 GPU 切换、回退原因、TensorRT 失败详情，目前 
  仅有基础日志，缺乏更细的监控项。定义日志/metrics 字段，后续可对接 Prometheus；先在日志中输出 JSON 行便于收集。                                                    
                                                                                      
  后续如果要彻底收尾 Stage 7，可以按上面的空缺逐项推进：完善 GPU 管线与测试、实现     
  WHIP/WHEP、补齐前端展示和监控体系。