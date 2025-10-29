# 路线图总览

- 里程碑 M0：打通只读接口与基本播放
  - 目标：`/api/models|/pipelines|/graphs` 返回数据库数据；分析页通过 WHEP 正常播放。
  - 验收：接口 200 且 data 非空；SSE phase=ready；<video> 10s 内 playing。
- 里程碑 M1：稳定化与可观测
  - 目标：CP⇄DB 稳定（P95<80ms），WHEP 201/ICE 成功率提升；日志与指标接入。
  - 验收：DB 查询错误率 <1%；WHEP 建连成功率 ≥95%；关键指标入库。
- 里程碑 M2：性能与CI守护
  - 目标：VA GPU 路径可控（保留 CPU 回退）；端到端回归在 CI 自动验证。
  - 验收：GPU on/off 开关可测；CI 绿灯；回放 FPS 与检测量稳定。

# 分阶段计划（表格）
| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| P0 | 三接口打通 | Classic Connector/C++；DLL 就位；SQL 映射 | 认证/依赖缺失→日志+调试路由 | 200 且 data 非空 |
| P1 | WHEP 播放可靠 | SSE 就绪→WHEP POST/ICE；前端事件校验 | NAT/证书问题→代理与证据采集 | 10s 内 playing |
| P1.5 | 可观测增强 | 指标/日志字段标准化；错误聚合 | 噪声→采样与阈值治理 | P95<80ms，错误<1% |
| P2 | GPU 路径与CI | IoBinding 开关；CPU 回退；回归用例 | 驱动/依赖差异→回退保护 | CI 全绿 |

# 依赖矩阵
- 内部依赖：
  - CP 路由/DB 模块；VA WHEP/Watch；前端分析页与 Vite 代理；VSM 源管理。
- 外部依赖（库/服务/硬件）：
  - MySQL 8（端口 13306）；Connector/C++ 9.4；可选 ODBC/MySQL X。
  - OpenSSL；ONNX Runtime（GPU 可选 CUDA）；Node.js；NVIDIA 驱动（如启用 GPU）。

# 风险清单（Top-5）
- Classic 认证失败 → 缺 RSA/插件不匹配 → 接口 data 为空 → 增加异常明文与调试路由，允许 ODBC/X 旁路
- 运行期 DLL 缺失 → 加载失败 → 事件日志含 “module not found” → 从 VA 产物拷贝 DLL 并随 CP 发布
- WHEP 建连异常 → NAT/证书/端口 → DevTools 无 playing → 代理到本机、校验证书、保存取证截图
- SQL 映射不一致 → 字段缺失/类型错 → JSON 结构异常 → 增加列到字段的映射测试与回退
- 性能波动 → P95 升高 → 指标抖动与超时 → 加索引/连接池与重试，压测后再放量
