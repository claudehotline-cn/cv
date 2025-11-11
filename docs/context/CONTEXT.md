# Triton 模型仓库管理与订阅改造（对话要点汇总）

本文汇聚本轮对话中已落地的设计、代码改动、接口与前端行为，作为持续迭代的上下文依据。

## 一、架构边界与通信

- 前端 → 控制平面（CP）：HTTP（/api/...）。
- 控制平面（CP） → 视频分析器（VA）：gRPC（AnalyzerControl）。
- VA 内部：Triton In‑Process Server（可选自动轮询、显示加载/卸载）。

## 二、核心能力与接口

1) 仓库列表与管理
- gRPC 新增/增强（video-analyzer/proto/analyzer_control.proto）
  - RepoList(RepoListRequest) → RepoListReply{ ok,msg, models[] }
    - RepoModel 字段扩展：id, path?, ready?, versions?[], active_version?
  - RepoLoad/RepoUnload/RepoPoll 保持可用。
  - RepoGetConfig/RepoSaveConfig：读取/写入 config.pbtxt（FS/MinIO S3，SigV4）。
- CP HTTP 路由（controlplane/src/server/main.cpp）
  - GET  /api/repo/list           → 优先详细字段，失败回退 id-only。
  - POST /api/repo/load|unload|poll
  - GET  /api/repo/config?model=… → 读取 config.pbtxt
  - POST /api/repo/config         → 保存 config.pbtxt
  - CORS 统一在入口设置，去除了局部重复头（修复 "'*, *'" 问题）。

2) 订阅使用仓库模型名
- CP /api/subscriptions（POST）：若 body.model_id 命中 RepoList（即仓库模型名），则仅设置 VA SetEngine.options.triton_model=model_id，并清空 model_id 后转发订阅；不切换 provider（provider=triton 已由配置确定）。

3) 别名治理（最小可用）
- /api/models/aliases：GET/POST/DELETE，内存 + 文件持久化（logs/model_aliases.json；CP_ALIASES_FILE 可覆盖）。
- /api/control/release：支持 alias 字段，解析为 triton_model[/version]（显式值优先）。

4) 可观测与指标
- /api/_metrics/summary 中新增 repo 操作计数（ok/fail for load/unload/poll/list）。
- 统一请求计数/直方图/下游 gRPC 错误统计。

## 三、VA Host 与会话

- TritonInprocServerHost（video-analyzer/src/analyzer/triton_inproc_server_host.*）
  - 新增 repository_poll_secs 选项；当 model_control=poll 且 >0 时，后台线程周期性 PollModelRepository。
  - load/unload/poll 加锁串行化；currentLoadedModels() 提供 ready 标记依据。
- TritonInprocModelSession/Factory 支持 triton_repository_poll_secs 选项透传。

## 四、前端改造（web-front）

- 模型页（src/views/Models.vue）
  - 数据源：优先 /api/repo/list（仓库），回退 /api/models（检测模型）。
  - 列展示：仓库模式显示 ready/versions/active_version，隐藏任务/系列/变体/输入尺寸/参数量；检测模型模式反之。
  - 操作：Load/Unload/Poll；“查看配置”按钮打开 Drawer。
  - 配置 Drawer：
    - 宽度 30%；浅色容器；换行/字号控制；复制/下载；
    - 语法高亮（关键词/常量/数字/字符串/注释），200KB/2000 行上限，避免卡顿；
    - 编辑模式（textarea）+ 保存/重载 → /api/repo/config（POST/GET）。
- API 封装（src/api/cp.ts）
  - repoList()/repoLoad()/repoUnload()/repoPoll()
  - repoConfig(model)/repoSaveConfig(model, content)

## 五、使用示例（HTTP）

- 列表：GET /api/repo/list
- 载入：POST /api/repo/load {"model":"yolov12x"}
- 订阅：POST /api/subscriptions {"stream_id":"cam01","profile":"default","source_uri":"rtsp://…","model_id":"yolov12x"}
- 配置：GET /api/repo/config?model=yolov12x；POST /api/repo/config {"model":"yolov12x","content":"…"}
- 别名：POST /api/models/aliases {"alias":"prod","model_id":"yolov12x","version":"1"}
- 发布：POST /api/control/release {"pipeline_name":"p","node":"det","alias":"prod"}

## 六、分支与提交（IOBinding）

- 关键提交：
  - RepoList 细节返回：8b01da4
  - CORS 修复：3767499
  - 别名治理最小实现：c405173；Release 联动别名：7021d48
  - VA Host 自动轮询与并发保护：62b5b7c；<thread> 构建修复：68965d8
  - 前端模型页增强与 Drawer：eebf191/82f5e31/1fcc231/3b5930f/686f8ef
  - 配置读写链路（VA/CP/前端）：6e65bcc/4354c8f/101d987

## 七、注意事项

- 订阅的 model_id 若为仓库模型名，将全局更新 triton_model；若需每订阅独立模型，需后续改 Pipeline 粒度注入。
- S3 写入/读取依赖环境变量：AWS_ENDPOINT_URL_S3/AWS_ENDPOINT_URL、AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY、AWS_REGION（或 S3_* 同义）。
- 大文件渲染采用行分割与长度上限，避免浏览器卡顿；必要时可进一步分页或虚拟化。
