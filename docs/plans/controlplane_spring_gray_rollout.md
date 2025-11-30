## controlplane Spring 灰度发布与回滚实施说明

### 1. 目标与前提

- 目标：在不影响现有 C++ 版 ControlPlane（CP）的前提下，引入 Spring 版 controlplane-spring，并通过灰度方式逐步切换流量；在任一阶段出现问题时可快速回滚。
- 前提：
  - C++ CP 与 cp-spring 都在同一 docker compose 网络中运行（服务名分别为 `cp` 与 `cp-spring`）。
  - VA/VSM/MySQL 等下游依赖保持兼容；cp-spring 已通过 `controlplane/test/scripts` 的主要用例验证。

### 2. 灰度架构概览

- 端口与域名：
  - C++ CP：容器内 `0.0.0.0:18080`，通过内部服务名 `cp:18080` 访问；
  - cp-spring：容器内 `0.0.0.0:18080`，通过服务名 `cp-spring:18080` 访问，并映射到宿主 `18080:18080`。
- 接入方：
  - web-frontend：通过可配置的 `CP_BASE_URL` 指向目标 CP；
  - Agent：通过 `AGENT_CP_BASE_URL` 控制请求落到 C++ CP 还是 cp-spring。

### 3. 灰度切换步骤（示例）

1. **准备阶段**
   - 确认 VA/VSM/MySQL 正常运行，C++ CP 所有脚本用例 PASS。
   - 构建并启动 cp-spring：`docker compose build cp-spring && docker compose up -d cp-spring`。
   - 使用 `CP_BASE_URL=http://127.0.0.1:18080` 对 cp-spring 跑一遍核心脚本（系统信息、订阅、sources、SSE 等），记录结果。

2. **小流量灰度（内部账号）**
   - 在 Agent 或前端配置中，为少量测试用户/线程设置 `AGENT_CP_BASE_URL` 或 `CP_BASE_URL` 指向 cp-spring，其余仍指向 C++ CP。
   - 使用 Grafana 控制平面仪表盘 + Prometheus 指标观察：
     - HTTP QPS/延迟；
     - gRPC 下游错误率（VA/VSM）；
     - SSE 连接数与事件速率。
   - 若错误率与延迟在可接受范围内，进入下一阶段；否则按第 5 节回滚。

3. **放大流量**
   - 按 10%→50%→100% 的比例逐步增加指向 cp-spring 的前端/Agent 调用。
   - 每一步放量后重复脚本回归与指标观察，确保未引入新的 5xx 或行为分裂。

4. **完全切换**
   - 当前端与 Agent 全部指向 cp-spring 且观察期内无异常，则可以将 C++ CP 标记为备份，仅保留最小监控/只读入口。

### 4. 回滚预案

1. **配置级回滚**
   - 将所有 `CP_BASE_URL/AGENT_CP_BASE_URL` 从 `cp-spring` 改回指向 C++ CP（例如 Nginx upstream 或环境变量），并重新加载配置。
   - 配置文件统一存入 Git，并提供简短的回滚脚本，做到“一条命令”完成切换。

2. **流量级回滚（代理层）**
   - 若使用反向代理（Nginx/Ingress），为 C++ CP 与 cp-spring 配置独立 upstream：
     - 灰度期间按权重分发流量（例如 `cp=9, cp-spring=1`）；
     - 发生问题时将 cp-spring 权重立即调整为 0，所有流量切回 C++ CP。

3. **数据一致性注意事项**
   - 灰度初期建议让 cp-spring 只承担读请求或幂等写操作，避免出现“部分写在 Spring CP，部分写在 C++ CP”导致的状态分裂。
   - 如确需写操作，应确保 DB 层 schema 完全一致，并在回滚前评估是否需要迁移/回放 cp-spring 期间产生的写入。

4. **演练与记录**
   - 在测试环境中至少执行一次完整流程：C++ CP→cp-spring 灰度切换→观察→回滚至 C++ CP。
   - 将关键操作命令、耗时与观测结果记录在 `docs/memo` 中，为生产变更提供可重复 SOP。

