# controlplain 推进计划

## 里程碑
- M0 最小可用（2–3 天）
  - 拆出 controlplain 工程骨架（CMake/配置/可运行）
  - 实现最小路由：POST/GET/DELETE /api/subscriptions 与 SSE 转发
  - 聚合 /api/system/info（只需核心字段）
  - 前端 baseURL 切换到 controlplain（开发环验证）
- M1 能力完善（3–5 天）
  - 接入 VSM 管理接口（list/attach/detach），补充只读缓存
  - 指标 cp_* 暴露与告警规则；失败分类（va|vsm）
  - 重试/熔断策略与建议头（X-Quota-*）透出
- M2 生产化（5–7 天）
  - 高可用：多实例 + 负载均衡；mTLS/Token（可选）
  - 版本能力探测与降级；灰度发布策略
  - 文档/运维手册与完整 E2E 测试

## 实施步骤（项点列表）
1) 工程骨架
- 新建 `controlplain/`：`CMakeLists.txt`、`src/server/*`、`include/controlplain/*`、`config/app.yaml`
- 配置 gRPC/Protobuf 生成；添加 Windows 构建脚本 `tools/build_controlplain_with_vcvars.cmd`
- 输出：可启动 HTTP 端口（空路由 200）、/health

2) gRPC 客户端封装
- 生成并封装 VA 的 AnalyzerControl 与 VSM 的 SourceControl 客户端
- 统一超时/重试/错误映射；最小连接复用
- 输出：最小单测/本地验证脚本

3) REST ⇄ gRPC 适配（M0）
- POST/GET/DELETE /api/subscriptions：转发到 VA；兼容 202+Location、ETag/304
- SSE /api/subscriptions/{id}/events：轮询/长连转发 phase 事件
- 输出：最小 API 脚本通过（POST→GET→DELETE+SSE）

4) system.info 聚合（M0）
- 从 VA/VSM 拉取系统信息与源集合；拼装为现有 JSON 结构
- 可选只读缓存（1–2s）
- 输出：脚本比对关键字段与来源 `source=config|env`

5) VSM 管理（M1）
- REST：/api/sources（list/attach/detach）转发到 VSM
- 输出：脚本 attach/detach 循环与源状态快照

6) 观测与告警（M1）
- 暴露 `cp_request_total`、`cp_latency_seconds`、`cp_backend_failure_total`
- 定义 P95/P99、后端失败率告警；输出示例 dashboard

7) 重试/熔断与建议（M1）
- 后端熔断窗口与恢复策略；429 路径建议头（X-Quota-*）
- 输出：故障注入脚本（va/vsm down）可复现并通过

8) 安全与版本（M2）
- 可选开启 JWT/OIDC、mTLS/Token；后端能力探测与降级
- 输出：文档与样例配置

9) 迁移与回滚
- 前端 baseURL 切换指南；VA 内嵌 CP 编译开关关闭
- 回滚：前端切回 VA 或重开内嵌开关

## 验证清单
- 最小 API、SSE、system.info 聚合均通过；
- VSM list/attach/detach 可用；
- 指标齐全且无高基数；
- 故障注入（va|vsm down）表现为可观测的优雅失败；
- 回滚脚本可在 5 分钟内完成切换。
