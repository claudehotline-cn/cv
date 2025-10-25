# 路线图总览

- 里程碑 M0：REST 语义加固与模块化
  - 目标：拆分 `rest.cpp`、规范 POST 202+Location、GET ETag/304、取消/失败 reason 统一。
  - 验收：接口向后兼容；脚本 `check_headers_cache.py`、`check_etag_race.py` 通过。

- 里程碑 M1：WAL 与预热最小闭环
  - 目标：订阅 WAL 持久化与重启扫描；模型预热与缓存指标；系统/指标回显完善。
  - 验收：`/admin/wal/*` 可用、`failed_restart>0`（演示环境）、`check_wal_scan.py`、`check_preheat_status.py` 通过。

- 里程碑 M2：配额/ACL 灰度与观测
  - 目标：observe_only/enforce_percent、per-key 覆盖、动态 Retry-After；Grafana 面板补齐；SSE/Codec 观测。
  - 验收：`check_quota_*`、`check_acl_profile_scheme.py`、`check_metrics_exposure.py` 通过；面板字段齐全。

# 分阶段计划（表格）
| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| M0 | REST 拆分+语义 | 202+Location、ETag/304、统一 reason | 历史兼容→保留旧字段；集中回归 | 脚本全绿，无 5xx |
| M1 | WAL+预热 | JSONL+TTL、扫描、预热并发/列表、cache 指标 | I/O 写放大→限速/滚动；重启校验 | failed_restart 指标有效 |
| M2 | 配额/ACL 灰度 | observe_only、enforce_percent、per-key override、动态 Retry-After | 误封风险→建议/Headers 透出 | dropped/would_drop 合理 |
| 观测 | 指标与系统信息 | 订阅队列/在途/状态、duration 直方图、SSE/Codec/WAL 指标 | 基数膨胀→低维度聚合 | `metrics_exposure` 通过 |
| CI/脚本 | 烟囱与 e2e | pwsh orchestration、Python 脚本、最小 API | Windows 构建易波动→Stop-Process | 关键脚本可重复通过 |

# 依赖矩阵
- 内部依赖：
  - VA ↔ CP（gRPC/REST）；VA ↔ VSM（gRPC/REST）；VA ↔ web-front（HTTP/SSE）。
  - ModelRegistry、CodecRegistry、WAL、DB 仓库、EngineManager。
- 外部依赖（库/服务/硬件）：
  - MySQL（127.0.0.1:13306）、RTSP 服务；Prometheus/Grafana；可选 CUDA/NVDEC/NVENC；CMake/VS Toolchain。

# 风险清单（Top-5）
- 链接失败（Windows 进程占用） → 构建时进程未停 → 监控 Stop-Process 结果 → 构建前强制终止并重试。
- RTSP/网络抖动 → Soak 报错偏高 → 统计 err/ok 与错误类型 → 延长超时/降并发/重试退避。
- WAL 旋转/TTL 边界 → 扫描遗漏或重复 → 采集 tail 证据与重启对比 → 增加去重与校验脚本。
- 指标基数膨胀 → Phase/Reason 标签过多 → 监控系列数 → 固定标签集+低维度聚合。
- 配额灰度误伤 → 策略配置错误 → 观察-only 先行+Headers 建议 → 分阶段放量+回滚预案。

