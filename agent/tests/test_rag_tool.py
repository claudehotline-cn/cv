from __future__ import annotations

from typing import Any, Dict, List

import pytest

from cv_agent.tools import rag as rag_mod


class _DummySettings:
    def __init__(self) -> None:
        self.rag_embedding_provider = "openai"
        self.openai_api_key = "test-key"


class _DummyEmbeddings:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.last_query: str | None = None

    def embed_query(self, query: str) -> List[float]:
        self.last_query = query
        return [0.1, 0.2, 0.3]


def _fake_search_kb(
    collection: str,
    embedding: List[float],
    top_k: int = 5,
    *,
    module: str | None = None,
    doc_type: str | None = None,
) -> List[Dict[str, Any]]:
    # 验证过滤条件与基本参数透传正确
    assert collection == "cv_docs"
    assert top_k == 3
    assert module == "cp"
    assert doc_type == "design"
    assert embedding  # 简单校验非空
    return [
        {
            "id": 1,
            "title": "ControlPlane Design",
            "path": "design/controlplane.md",
            "chunk_index": 0,
            "content": "control plane design snippet",
        }
    ]


def test_search_cv_docs_tool_filters_and_maps_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """search_cv_docs_tool 应正确透传过滤条件并返回结构化片段。"""

    monkeypatch.setattr(rag_mod, "get_settings", lambda: _DummySettings())
    monkeypatch.setattr(rag_mod, "OpenAIEmbeddings", _DummyEmbeddings)
    monkeypatch.setattr(rag_mod, "search_kb", _fake_search_kb)

    params = rag_mod.SearchCvDocsInput(
        query="control plane design",
        collection="cv_docs",
        module="cp",
        doc_type="design",
        top_k=3,
    )

    rows = rag_mod.search_cv_docs_tool(params)

    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == 1
    assert row["title"] == "ControlPlane Design"
    assert row["path"] == "design/controlplane.md"
    assert row["chunk_index"] == 0
    assert "snippet" in row
    assert "control plane" in row["snippet"]

