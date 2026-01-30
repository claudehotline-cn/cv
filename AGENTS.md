# AGENTS.md

本仓库是一个多服务单仓（Python + Docker + 一个小型 Vue UI）。本文件用于给各类 agentic coding agent（包括我自己）提供工作约定。

## 现有 Agent 规则（Cursor/Copilot）
- 未发现仓库级 Cursor 规则（`.cursor/rules/`、`.cursorrules` 均不存在）。
- 未发现仓库级 Copilot 规则（`.github/copilot-instructions.md` 不存在）。
- 注意：`third-party/langgraph/AGENTS.md` 存在，但仅适用于 vendored 的 LangGraph 代码。

## 项目结构（哪些是“核心”）
- `agent-platform-api/`：FastAPI 控制面 + ARQ worker（Docker 中为 `agent-api`/`agent-worker`）。
- `agent-core/`：共享 runtime/middleware/settings（被 agents 和 plugins 复用）。
- `agent-plugins/`：插件/agent 图；每个插件可能有自己的 `tests/`。
- `agent-audit/`：审计事件 emitter + instrumentation；平台与插件都会用。
- `agent-test/`：测试工具包（fixtures/mocks/evaluators），CI/本地测试会用。
- `agent-cli/`：脚手架/管理 CLI（Typer），用于生成/管理插件。
- `rag_service/`：RAG 知识库服务（FastAPI + ARQ worker，Docker 中为 `rag-service`/`rag-worker`）。
- `agent-chat-vue/`：Vue 3 + Vite UI。
- `docker/compose/docker-compose.yml`：本地开发栈（MySQL、pgvector、redis、minio、neo4j、vLLM、各服务）。
- `third-party/`：第三方代码/示例；除非明确要求，避免修改。

## 构建 / 运行（Docker 优先）

### 启动完整环境
compose 里定义了很多服务；vLLM 在 profile `vllm` 下。

1) 启动基础设施 + 服务（CPU）：
```bash
docker compose -f docker/compose/docker-compose.yml up -d mysql pgvector redis minio neo4j agent-api agent-worker rag-service rag-worker
```

2) 启动 vLLM（GPU profile）：
```bash
docker compose -f docker/compose/docker-compose.yml --profile vllm up -d vllm
```

3) 可选 UI：
```bash
docker compose -f docker/compose/docker-compose.yml up -d agent-chat-vue
```

### 代码/依赖变更后重建镜像
```bash
docker compose -f docker/compose/docker-compose.yml build rag-service rag-worker agent-api agent-worker
docker compose -f docker/compose/docker-compose.yml --profile vllm build vllm
```

### 快速健康检查
```bash
curl -fsS http://localhost:18111/health   # agent-platform-api
curl -fsS http://localhost:18200/health   # rag-service
curl -fsS http://localhost:18000/health   # vLLM
```

### 常用开发命令
```bash
docker compose -f docker/compose/docker-compose.yml ps
docker logs --tail 200 agent-api
docker logs --tail 200 rag-service
docker restart agent-api agent-worker rag-service rag-worker
```

### 服务入口（容器内）
- Agent API：`uvicorn app.main:app`（见 `agent-platform-api/Dockerfile`）
- Agent worker：`arq app.worker.WorkerSettings`（compose `agent-worker`）
- RAG API：`uvicorn rag_service.main:app`（见 `docker/rag-service/Dockerfile`）
- RAG worker：`arq rag_service.worker.WorkerSettings`（compose `rag-worker`）

### RAG 常用运维（HTTP）
```bash
curl -fsS http://localhost:18200/api/knowledge-bases
curl -fsS -X POST http://localhost:18200/api/knowledge-bases/1/rebuild-vectors
curl -fsS -X POST http://localhost:18200/api/knowledge-bases/1/build-graph
```

## 测试（pytest）

pytest 配置在 `pytest.ini`：`asyncio_mode = strict`，并定义了 markers：`unit`/`integration`。

### 推荐（Docker 内跑）
```bash
docker compose -f docker/compose/docker-compose.yml up -d agent-test
docker exec agent-test pytest -q
```

### 在宿主机直接跑（需要安装可编辑包）
```bash
python -m pip install -e agent-core -e agent-test
PYTHONPATH=$PWD/agent-audit:$PWD/agent-core:$PWD/agent-test:$PWD/agent-plugins:$PWD pytest -q
```

### 运行全部测试
```bash
pytest -q
```

### 运行单个测试文件
```bash
pytest -q agent-core/tests/test_audit.py
pytest -q rag_service/tests/unit/test_image_encoder.py
```

### 运行单个测试函数
```bash
pytest -q agent-core/tests/test_audit.py::test_audit_emitter
```

### 只跑 unit / integration
```bash
pytest -q -m unit
pytest -q -m integration
```

### 插件测试循环（与 CI 一致）
CI 会遍历插件并运行 tests（`.github/workflows/agent-tests.yml`）：
```bash
for dir in agent-plugins/*/; do
  if [ -d "$dir/tests" ]; then pytest -q "$dir/tests"; fi
done
```

## Lint / Format

仓库根目录没有统一的 linter 配置（没有 `ruff.toml`、`.pre-commit-config.yaml` 等）。

### Python（尽力而为）
```bash
python -m compileall -q . && python -m pip install -q black isort && black --check . && isort --check-only .
```

### 前端（agent-chat-vue）
```bash
cd agent-chat-vue
npm install
npm run build     # vue-tsc + vite build
```

## 代码风格约定

- 格式：4 空格缩进；行宽建议 ~100；优先 f-string；简单容器用 dataclass；API schema 用 Pydantic v2。
- 导入：stdlib/third-party/local 分组；避免 `import *`；包内优先显式相对导入。
- 类型：公共 API 写类型标注；可空用 `Optional[T]`（或文件内已统一用 `T | None` 时跟随）；Pydantic v2 用 `.model_dump()` / `.model_dump_json(exclude_none=True)`。
- 命名：文件/模块 `snake_case.py`；函数/变量 `snake_case`；类 `PascalCase`；常量 `UPPER_SNAKE_CASE`。
- 错误/日志：FastAPI 层用 `HTTPException`；服务层校验用 `ValueError`；日志带标识（`kb_id`、`doc_id`、`job_id`）。
- 异步：`async def` 里不要阻塞；HTTP 用 `httpx.AsyncClient`；重任务走 ARQ job（不要在 request handler 里做重活）。
- DB/SQL：及时关闭 SQLAlchemy session；SQL 尽量参数化（避免 f-string SQL）；embedding 维度迁移时保留旧 pgvector 表以便回滚。
- RAG 路由：Embeddings=Ollama（`settings.ollama_base_url`）；LLM/VLM=vLLM（`settings.vllm_base_url`）；reranker=本地 `sentence-transformers` CrossEncoder。
- 环境变量：平台侧多用 `AGENT_*`/`DATABASE_URL`/`REDIS_URL`；RAG 用 `RAG_*`；vLLM OpenAI API：`http://localhost:18000/v1`。

## 常见坑
- ARQ 队列冲突：使用独立队列名（例如 `RAG_QUEUE_NAME=rag:queue`），避免不同 worker 抢同一个默认队列。
- 文档加载时注意文件后缀；部分 loader 会根据 suffix 决定解析逻辑。
- 非必要不要改 `third-party/`：该目录有自己的约定/工具链。

## agent-cli（脚手架）
```bash
python -m pip install -e agent-cli
agent-cli --help
```
## mcp 服务
- 更多 langchain 开发文档可以使用 Langchain-doc mcp 服务
- 其他开发文档可以使用 context7 的 mcp 服务

**请使用中文与我交流。**