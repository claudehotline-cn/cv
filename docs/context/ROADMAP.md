# 路线图总览

- M0｜可管可见的仓库与订阅
  - 目标：打通 Triton 仓库管理（列出/加载/卸载/轮询）、订阅可直接使用仓库模型名、前端可视化与配置查看。
  - 验收：/api/repo/* 可用；/api/subscriptions 接受仓库模型名；前端展示 ready/versions 并可查看/编辑/保存 config.pbtxt。
- M1｜别名与发布治理
  - 目标：以别名（alias）管理模型/版本，支持通过 alias 发布/回滚。
  - 验收：/api/models/aliases CRUD；/api/control/release 支持 alias→triton_model[/version]；（可选）前端别名管理面板。
- M2｜自动轮询/预热与可观测
  - 目标：VA Host 自动 Poll，最小预热；CP 增强指标与错误画像；前端轻量运维视图。
  - 验收：repository_poll_secs 生效；/_metrics/summary 暴露 repo 指标；（可选）前端展示健康度与最近错误。

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
| ---- | ---------- | -------- | --------- | -------- |
| M0 | RepoList/Load/Unload/Poll；订阅直用仓库名；配置读写 | RepoModel 扩展(ready/versions)；CP 订阅前探测 RepoList；config.pbtxt FS/S3 读写 | S3 权限/签名失败→回退FS/明确错误；CORS 冲突→统一入口设置 | /api/repo/* 成功率>99%；列表TTFB<300ms |
| M0 | 前端模型页与 Drawer | 仓库/检测模式动态列；语法高亮与性能上限；复制/下载/编辑/保存 | 大文件渲染卡顿→按行处理+上限；样式干扰→隔离样式 | 2s 内渲染 200KB/2000 行 |
| M1 | 别名 CRUD + 发布联动 | 内存+文件持久化；/api/control/release 解析 alias | 状态不一致→保存后回读校验；误发布→最小回滚路径 | alias CRUD 成功率>99%；发布 1 次点击 |
| M2 | VA Host 自动轮询与预热 | repository_poll_secs；load/unload/poll 串行化；预热钩子 | 线程稳定性→有序退出；资源抖动→限频 | 轮询线程存活率≈100% |
| M2 | 可观测与错误画像 | /api/_metrics/summary 增加 repo ok/fail；Prom 指标 | 指标漂移→归一口径；维度过细→分级聚合 | 指标开销<5% CPU |

# 依赖矩阵

- 内部依赖：
  - CP metrics/cache/HTTP 栈；VA AnalyzerControl gRPC 服务；前端 Models.vue
- 外部依赖（库/服务/硬件）：
  - Triton Server In‑Process SDK；MinIO/S3（SigV4）；CUDA/NVENC；gRPC；浏览器运行环境

# 风险清单（Top-5）

- S3 读写失败/超时 → 凭证/端点错误或网络不稳 → /api/repo/config 失败率上升 → 回退到FS/明确错误、增加重试与告警。
- 全局 triton_model 切换影响其他订阅 → 在高并发发布场景触发 → 现网订阅质量瞬时下降 → 明确“全局切换”提示，推进 Pipeline 级模型注入改造。
- 大配置渲染卡顿 → 超大 pbtxt/低端机器 → 前端卡住/卡顿 → 行分割+上限、支持分页/下载离线查看。
- 后台轮询线程异常退出 → 罕见崩溃/资源耗尽 → 仓库变更未生效 → 加入存活检查与限频、统一退出流程。
- CORS/安全策略冲突 → 前端跨源访问策略调整 → 浏览器拒绝请求 → 入口统一 CORS，禁用路由层重复头，暴露必要头字段。
