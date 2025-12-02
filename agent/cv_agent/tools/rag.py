from typing import List

from langchain_openai import OpenAIEmbeddings
from langchain_community.embeddings import OllamaEmbeddings
from pydantic import BaseModel, Field

from ..config import get_settings
from ..rag.pg_store import search_kb

try:
    from langchain_core.tools import tool
except Exception:
    try:
        from langchain.tools import tool  # type: ignore[no-redef]
    except Exception:

        def tool(*args, **kwargs):  # type: ignore[misc]
            def decorator(func):
                return func

            return decorator


class SearchCvDocsInput(BaseModel):
    """输入：基于 docs 知识库的检索请求。"""

    query: str = Field(description="自然语言查询内容")
    collection: str = Field(
        default="cv_docs",
        description="知识库集合名称，例如 cv_docs",
    )
    module: str | None = Field(
        default=None,
        description="可选模块名称（如 controlplane/va/web），将按 kb_docs.module 过滤。",
    )
    doc_type: str | None = Field(
        default=None,
        description="可选文档类型（如 design/plans/references/requirements），将按 kb_docs.doc_type 过滤。",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="返回的文档片段数量上限",
    )


@tool("search_cv_docs", args_schema=SearchCvDocsInput)
def search_cv_docs_tool(params: SearchCvDocsInput) -> List[dict]:
    """
    在 CV 项目的文档知识库中检索与 query 最相关的文档片段。

    当前实现：
    - 使用 OpenAI 或 Ollama embedding 模型将 query 转换为向量；
    - 在 PostgreSQL+pgvector 的 kb_docs 表中按集合名和向量相似度进行检索；
    - 返回若干结构化片段（标题、路径、片段内容），供 Agent 参考。

    依赖：
    - 当 `AGENT_RAG_EMBEDDING_PROVIDER=openai` 时需要配置 OPENAI_API_KEY；
    - 当 `AGENT_RAG_EMBEDDING_PROVIDER=ollama` 时需要本地或远程 Ollama 服务；
    - 需要正确配置 Agent 的 RAG PostgreSQL 连接参数，并提前建立 kb_docs 表与数据。
    """

    settings = get_settings()
    provider = (settings.rag_embedding_provider or "openai").lower()

    if provider == "ollama":
        embeddings = OllamaEmbeddings(
            base_url=settings.rag_ollama_base_url,
            model=settings.rag_ollama_model,
        )
    else:
        if not settings.openai_api_key:
            raise RuntimeError("未配置 OPENAI_API_KEY，无法计算查询向量。")
        embeddings = OpenAIEmbeddings(
            api_key=settings.openai_api_key,
            model="text-embedding-3-small",
        )

    embedding = embeddings.embed_query(params.query)

    rows = search_kb(
        collection=params.collection,
        embedding=embedding,
        top_k=params.top_k,
        module=params.module,
        doc_type=params.doc_type,
    )

    out: List[dict] = []
    for row in rows:
        out.append(
            {
                "id": row.get("id"),
                "title": row.get("title"),
                "path": row.get("path"),
                "chunk_index": row.get("chunk_index"),
                "snippet": row.get("content"),
            }
        )
    return out
