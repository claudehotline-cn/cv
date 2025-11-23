## Agent 服务最小 E2E 调用示例

本示例展示如何在 docker compose 环境下，通过 HTTP 调用新建的 Agent 服务，实现：

- 用户自然语言提问；
- Agent 使用 ReAct 模式自动调用 ControlPlane 的 `/api/pipelines` 工具；
- 返回包含 pipeline 信息的自然语言与结构化结果。

### 1. 启动 docker compose（包含 agent）

```bash
cd /home/chaisen/projects/cv
docker compose -f docker/compose/docker-compose.yml up -d agent
```

确保 `cp`、`mysql` 等依赖服务已启动后，`agent` 会通过健康检查变为 `healthy`。

### 2. 使用 curl 直接调用 HTTP 接口

```bash
curl -X POST http://localhost:18081/v1/agent/invoke \
  -H 'Content-Type: application/json' \
  -d '{
    "messages": [
      { "role": "user", "content": "请帮我列出当前所有 pipeline。" }
    ]
  }'
```

若一切正常，将返回形如：

- `message`: Agent 的自然语言回复；
- `raw_state`: LangGraph 状态（仅用于调试，可在生产中关闭）。

### 3. 使用 Python 脚本做最小 E2E 校验

仓库 `agent/test_invoke_agent.py` 提供了一个最小调用脚本：

```bash
cd /home/chaisen/projects/cv
python agent/test_invoke_agent.py
```

脚本会向 `http://localhost:18081/v1/agent/invoke` 发送“列出当前所有 pipeline”的请求，并将返回的 JSON 打印到终端。

### 4. OPENAI_API_KEY 与模型配置

Agent 容器依赖 OpenAI 兼容模型访问能力：

- 在启动 docker compose 前，在宿主机设置环境变量：

```bash
export OPENAI_API_KEY=你的密钥
```

- `docker/compose/docker-compose.yml` 中已将该变量透传到 `agent` 容器，同时通过
  `AGENT_OPENAI_MODEL=gpt-4o-mini` 指定默认模型。

如需更换为其他兼容模型，修改对应环境变量即可。

