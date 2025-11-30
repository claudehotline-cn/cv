import argparse
import os
from pathlib import Path
from typing import Iterable, List, Tuple

from langchain_community.embeddings import OllamaEmbeddings
from langchain_openai import OpenAIEmbeddings

from ..config import get_settings
from .pg_store import get_connection


def _discover_markdown_files(root: Path) -> List[Path]:
    """
    在 docs 目录下发现适合纳入知识库的 Markdown 文件。

    当前策略：
    - 包含以下子目录：
      - docs/design
      - docs/plans
      - docs/references
      - docs/requirements
    - 排除 docs/memo 与临时/资产文件。
    """

    patterns = [
        "design/**/*.md",
        "plans/**/*.md",
        "references/**/*.md",
        "requirements/**/*.md",
    ]
    results: List[Path] = []
    for pattern in patterns:
        results.extend(root.glob(pattern))
    return sorted(set(p for p in results if p.is_file()))


def _load_markdown(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _extract_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            # 去掉 Markdown 标题前缀
            return line.lstrip("#").strip() or fallback
    return fallback


def _split_into_chunks(text: str, max_chars: int = 1200, overlap: int = 200) -> List[str]:
    """
    将长文档按字符数粗粒度切片。

    - 优先保持段落完整（按空行划分）；
    - 每个分片最长 max_chars，前后分片之间 overlap 字符重叠。
    """

    paragraphs = text.split("\n\n")
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        plen = len(para)
        if current and current_len + plen + 2 > max_chars:
            chunks.append("\n\n".join(current))
            # 简单的重叠：从当前分片末尾截取 overlap 字符作为下一个起点
            if overlap > 0:
                tail = chunks[-1][-overlap:]
                current = [tail]
                current_len = len(tail)
            else:
                current = []
                current_len = 0
        current.append(para)
        current_len += plen + 2

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def _get_embeddings():
    """根据配置返回 OpenAI 或 Ollama 的 embedding 客户端。"""

    settings = get_settings()
    provider = (settings.rag_embedding_provider or "openai").lower()

    if provider == "ollama":
        return OllamaEmbeddings(
            base_url=settings.rag_ollama_base_url,
            model=settings.rag_ollama_model,
        )

    if not settings.openai_api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY，且 AGENT_RAG_EMBEDDING_PROVIDER=openai，无法构建知识库。")

    return OpenAIEmbeddings(
        api_key=settings.openai_api_key,
        model="text-embedding-3-small",
    )


def _ensure_schema(conn) -> None:
    """
    确保 pgvector 扩展和 kb_docs 表存在。

    结构与 `pg_store.search_kb` 文档中示例保持一致。
    """

    sql = """
        CREATE EXTENSION IF NOT EXISTS vector;
        CREATE TABLE IF NOT EXISTS kb_docs (
          id           BIGSERIAL PRIMARY KEY,
          collection   TEXT NOT NULL,
          doc_path     TEXT NOT NULL,
          doc_title    TEXT NOT NULL,
          chunk_index  INT  NOT NULL,
          content      TEXT NOT NULL,
          embedding    vector(1536) NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_kb_docs_collection ON kb_docs(collection);
        CREATE INDEX IF NOT EXISTS idx_kb_docs_embedding
          ON kb_docs USING ivfflat (embedding vector_l2_ops);
    """
    with conn.cursor() as cur:
        cur.execute(sql)


def _iter_chunks(root: Path) -> Iterable[Tuple[str, str, int, str]]:
    """
    遍历 docs 下的文档分片。

    返回：(doc_path, doc_title, chunk_index, content)。
    """

    files = _discover_markdown_files(root)
    for path in files:
        text = _load_markdown(path)
        rel_path = os.path.relpath(path, root)
        title = _extract_title(text, fallback=rel_path)
        chunks = _split_into_chunks(text)
        for idx, chunk in enumerate(chunks):
            yield rel_path, title, idx, chunk


def build_kb(
    docs_root: Path,
    collection: str = "cv_docs",
    reset_collection: bool = True,
) -> None:
    """
    从 docs 构建/刷新知识库分片到 kb_docs。

    - docs_root：通常为仓库内 `docs/` 目录；
    - collection：kb_docs.collection 字段，默认 `cv_docs`；
    - reset_collection：是否在写入前清空该 collection 下旧数据。
    """

    embeddings = _get_embeddings()
    conn = get_connection()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            if reset_collection:
                cur.execute("DELETE FROM kb_docs WHERE collection = %s", (collection,))

            rows: List[Tuple[str, str, int, str, str]] = []
            for doc_path, title, chunk_index, content in _iter_chunks(docs_root):
                vec = embeddings.embed_query(content)
                emb_literal = "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
                rows.append(
                    (collection, doc_path, title, chunk_index, content, emb_literal)
                )

            if rows:
                cur.executemany(
                    """
                    INSERT INTO kb_docs (collection, doc_path, doc_title, chunk_index, content, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s::vector)
                    """,
                    rows,
                )
    finally:
        conn.close()


def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="从 docs/ 构建 CV 项目知识库（kb_docs）"
    )
    parser.add_argument(
        "--docs-root",
        type=str,
        default="docs",
        help="文档根目录（默认：项目内 docs）",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default="cv_docs",
        help="kb_docs.collection 名称（默认：cv_docs）",
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="不在写入前清空该 collection 旧数据",
    )
    args = parser.parse_args(argv)

    root = Path(args.docs_root).resolve()
    if not root.exists():
        raise SystemExit(f"docs 根目录不存在：{root}")

    build_kb(
        docs_root=root,
        collection=args.collection,
        reset_collection=not args.no_reset,
    )


if __name__ == "__main__":  # pragma: no cover - 手工执行入口
    main()

