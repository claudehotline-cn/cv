# 路线图总览

- M0「REST 稳定化与拆分」：完成 `rest.cpp` 业务化拆分；POST 订阅返回 202+Location；GET 订阅支持 ETag/304；取消与 reason 归一。验收：构建通过、冒烟测试通过、Headers/ETag 用例通过。
- M1「WAL 与预热」：订阅事件 WAL 持久化+重启扫描；模型/编解码预热与状态曝光；指标完善与 Admin 只读接口。验收：WAL 计数器增长、`/admin/wal` 可用、`/system/info` 预热字段正确、相关脚本通过。
- M2「配额/ACL 灰度与压测」：observe_only/enforce_percent 灰度发布；ACL/Key 覆盖；Grafana 大盘完善；soak 稳定。验收：丢弃/将丢弃指标符合灰度预期；soak 误差低于阈值；面板可直观诊断。

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| M0 | REST 拆分+语义加固 | 路由拆分、ETag/304、202+Location、取消归一 | 回归多、接口行为变更 → 加冒烟与兼容层 | Headers/ETag 用例 100% 通过 |
| M1 | WAL 最小闭环、预热 | JSONL 滚动/TTL、重启扫描、后台预热 | IO 抖动/旋转错误 → 限流+重试+告警 | wal_failed_restart_total=0（常态） |
| M2 | 配额/ACL 灰度 | observe/enforce、key 覆盖、ACL 规则 | 误封或放行 → 灰度+白名单+只观察期 | dropped≤期望；would_drop≥dropped |
| 观测 | 指标/面板完善 | 阶段直方图、失败原因维度、配额看板 | 指标基数过高 → 采样+聚合 | 指标样本稳定、面板无报警 |
| CI/测试 | 脚本与 E2E | pwsh 编排、Python 脚本、MCP 取证 | Windows 环境差异 → 容错与超时提升 | 冒烟全绿，soak 误差<1% |

# 依赖矩阵

- 内部依赖：VA ⇄ VSM（gRPC/REST）；CP ⇄ VA/VSM（gRPC）；前端 ⇄ CP（HTTP）。
- 外部依赖（库/服务/硬件）：MySQL(127.0.0.1:13306)；RTSP 服务；Prometheus/Grafana；可选 CUDA/NVDEC/NVENC；CMake/VS 工具链。

# 风险清单（Top-5）

- Windows 链接占用 → 进程未停 → 构建失败/LNK1104 → 构建前 Stop-Process/端口检查。
- RTSP/网络抖动 → 并发/重试不足 → soak err 上升 → 提高超时与退避、并发降级、错误分类上报。
- 数据库不可用 → 源管理失败 → `/api/sources` 异常 → 启动前健康检查、重试与降级（只读缓存）。
- 指标基数过高 → 存储/面板卡顿 → 报警延迟 → 指标降维/采样、分桶与聚合控制。
- WAL 旋转/TTL 缺陷 → 扫描遗漏/膨胀 → 重启恢复异常 → 写入护栏、扫描校验、e2e 重启演练与告警。

