"""Ingestion / background processing.

These helpers are used by both the API (fallback BackgroundTasks) and the ARQ worker.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from ..database import MySQLSessionLocal
from ..models import Document, KnowledgeBase
from ..models import DocumentOutline

logger = logging.getLogger(__name__)


def _ensure_loader_filename(doc: Document) -> str:
    """Ensure the filename passed to DocumentLoader has a usable extension."""
    filename = (doc.filename or f"document_{doc.id}").strip()
    if Path(filename).suffix:
        return filename

    # Prefer the MinIO object suffix.
    ext = Path(doc.file_path or "").suffix
    if ext:
        return f"{filename}{ext}"

    # Fallback based on file_type.
    default_ext = {
        "pdf": ".pdf",
        "word": ".docx",
        "excel": ".xlsx",
        "markdown": ".md",
        "text": ".txt",
        "webpage": ".txt",
        "image": ".jpg",
        "audio": ".mp3",
        "video": ".mp4",
    }.get(doc.file_type or "", "")
    return f"{filename}{default_ext}" if default_ext else filename


async def process_document(document_id: int) -> None:
    """Process a Document by id and persist vectors.

    Updates:
    - rag_documents.status, chunk_count, error_message
    - pgvector rag_vectors (delete+reinsert)
    """
    from ..services.minio_service import minio_service
    from ..services.document_loader import document_loader
    from ..services.embedder import embedding_service
    from ..services.vector_store import vector_store
    from ..services.image_encoder import image_encoder
    from ..services.speech_service import speech_service
    from ..services.video_service import video_service
    from ..services.chunker import DocumentChunker
    from ..services.text_cleaner import apply_cleaning_rules

    with MySQLSessionLocal() as db:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            return

        doc.status = "processing"
        doc.error_message = None
        db.commit()

        if not doc.file_path:
            doc.status = "failed"
            doc.error_message = "Missing file_path (MinIO object name)"
            db.commit()
            return

        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.knowledge_base_id).first()

        kb_rules = None
        if kb and kb.cleaning_rules:
            try:
                import json as _json

                kb_rules = _json.loads(kb.cleaning_rules)
            except Exception:
                kb_rules = None

        local_path = minio_service.download_file(doc.file_path)
        if not local_path or not os.path.exists(local_path):
            doc.status = "failed"
            doc.error_message = f"Failed to download from MinIO: {doc.file_path}"
            db.commit()
            return

        try:
            # Always delete old vectors before re-inserting.
            vector_store.delete_document_vectors(doc.id)

            # Dispatch by modality / file_type.
            if doc.file_type == "image":
                embedding, description = await image_encoder.encode(local_path)
                description = apply_cleaning_rules(description or "", kb_rules)
                if embedding:
                    vector_store.store_vectors(
                        document_id=doc.id,
                        chunks=[
                            (
                                0,
                                description,
                                embedding,
                                {
                                    "type": "image",
                                    "filename": doc.filename,
                                    "minio_path": doc.file_path,
                                },
                            )
                        ],
                    )
                doc.chunk_count = 1
                doc.status = "completed"
                db.commit()
                return

            if doc.file_type == "audio":
                result = await speech_service.transcribe(local_path)
                transcript = apply_cleaning_rules(result.text or "", kb_rules)
                chunks = DocumentChunker(
                    chunk_size=(kb.chunk_size if kb else None),
                    chunk_overlap=(kb.chunk_overlap if kb else None),
                    preprocess=False,
                ).chunk(transcript, {"type": "audio", "language": result.language})

                texts = [c.content for c in chunks]
                embeddings = embedding_service.embed_texts(texts) if texts else []
                chunk_data = [
                    (
                        i,
                        c.content,
                        emb,
                        {
                            "type": "audio",
                            "language": result.language,
                            "minio_path": doc.file_path,
                            "filename": doc.filename,
                        },
                    )
                    for i, (c, emb) in enumerate(zip(chunks, embeddings))
                ]
                if chunk_data:
                    vector_store.store_vectors(doc.id, chunk_data)

                doc.chunk_count = len(chunk_data)
                doc.status = "completed"
                db.commit()
                return

            if doc.file_type == "video":
                analysis = await video_service.analyze(local_path, include_transcript=True)

                full_content = analysis.summary
                if analysis.transcript:
                    full_content += f"\n\nAudio transcript:\n{analysis.transcript}"

                full_content = apply_cleaning_rules(full_content, kb_rules)

                chunker = DocumentChunker(
                    chunk_size=(kb.chunk_size if kb else None),
                    chunk_overlap=(kb.chunk_overlap if kb else None),
                    preprocess=False,
                )
                chunks = chunker.chunk(full_content, {"type": "video"})

                texts = [c.content for c in chunks]
                embeddings = embedding_service.embed_texts(texts) if texts else []
                chunk_data = [
                    (
                        i,
                        c.content,
                        emb,
                        {
                            "type": "video",
                            "minio_path": doc.file_path,
                            "filename": doc.filename,
                        },
                    )
                    for i, (c, emb) in enumerate(zip(chunks, embeddings))
                ]
                if chunk_data:
                    vector_store.store_vectors(doc.id, chunk_data)

                doc.chunk_count = len(chunk_data)
                doc.status = "completed"
                db.commit()
                return

            # ===== Text-like documents =====
            loader_filename = _ensure_loader_filename(doc)
            loaded = document_loader.load(local_path, loader_filename)

            raw_text = loaded.content

            # Marker sometimes returns Markdown with headings flattened into a single line.
            # Normalize it so `# ...` headings start on their own lines, improving chunking + outline.
            try:
                import re as _re

                extraction = (loaded.metadata or {}).get("extraction")
                if extraction == "marker" and raw_text:
                    lines = str(raw_text).split("\n")

                    # Heuristic: drop a stray leading fence (```/~~~) if it isn't closed and a real heading appears soon.
                    first_idx = next((i for i, ln in enumerate(lines) if ln.strip()), None)
                    if first_idx is not None:
                        first = lines[first_idx].strip()
                        if first in ("```", "~~~"):
                            saw_close = False
                            saw_heading = False
                            for ln in lines[first_idx + 1 : first_idx + 60]:
                                t = ln.strip()
                                if not t:
                                    continue
                                if t == first:
                                    saw_close = True
                                    break
                                if _re.match(r"^\s*(?:>\s*)?#{1,6}\s+\S+", ln):
                                    saw_heading = True
                                    break
                            if saw_heading and not saw_close:
                                lines.pop(first_idx)

                    out_lines: list[str] = []
                    in_code = False
                    fence = None
                    for line in lines:
                        t = line.strip()
                        if t.startswith("```") or t.startswith("~~~"):
                            f = t[:3]
                            if not in_code:
                                in_code = True
                                fence = f
                            elif fence == f:
                                in_code = False
                                fence = None
                            out_lines.append(line)
                            continue

                        if in_code:
                            out_lines.append(line)
                            continue

                        # Split inline headings onto their own lines.
                        normalized = _re.sub(r"\s+(#{1,6})\s+", r"\n\\1 ", line)
                        out_lines.extend(normalized.split("\n"))

                    raw_text = "\n".join(out_lines)
            except Exception:
                pass

            # Markdown-like docs (e.g., marker PDF->Markdown) should keep heading lines intact.
            # The default rule `consolidateShortParagraphs` can merge headings into previous paragraphs,
            # breaking outline extraction and heading-aware chunking.
            structure_rules = kb_rules
            try:
                import re as _re

                in_code = False
                fence = None
                heading_lines = 0
                for line in str(raw_text or "").split("\n"):
                    t = line.strip()
                    if t.startswith("```") or t.startswith("~~~"):
                        f = t[:3]
                        if not in_code:
                            in_code = True
                            fence = f
                        elif fence == f:
                            in_code = False
                            fence = None
                        continue
                    if in_code:
                        continue
                    if _re.match(r"^\s*(?:>\s*)?#{1,6}\s+\S+", line):
                        heading_lines += 1
                        if heading_lines >= 2:
                            break

                if heading_lines >= 2 and isinstance(kb_rules, dict):
                    structure_rules = {**kb_rules, "consolidateShortParagraphs": False}
            except Exception:
                pass

            cleaned = apply_cleaning_rules(raw_text, structure_rules)

            chunker = DocumentChunker(
                chunk_size=(kb.chunk_size if kb else None),
                chunk_overlap=(kb.chunk_overlap if kb else None),
                preprocess=False,
            )

            # Try markdown-aware chunking first; it will auto-fallback if not markdown-like.
            parent_chunks, child_chunks = chunker.markdown_hierarchical_chunk(
                content=cleaned,
                metadata=loaded.metadata,
                child_max_size=(kb.chunk_size if kb else 500),
                child_overlap=(kb.chunk_overlap if kb else 50),
            )

            # Persist document outline based on extracted Markdown headings.
            # This is independent from the chunk list UI; we only attach a best-effort mapping
            # to parent chunk_index for scroll-to-section.
            try:
                import json as _json
                import re as _re

                def _extract_markdown_headings(md: str) -> list[tuple[int, str]]:
                    lines = str(md or "").split("\n")
                    in_code = False
                    fence = None
                    out: list[tuple[int, str]] = []
                    for line in lines:
                        t = line.strip()
                        if t.startswith("```") or t.startswith("~~~"):
                            f = t[:3]
                            if not in_code:
                                in_code = True
                                fence = f
                            elif fence == f:
                                in_code = False
                                fence = None
                            continue
                        if in_code:
                            continue

                        m = _re.match(r"^\s*(?:>\s*)?(#{1,6})\s+(.+?)\s*$", line)
                        if not m:
                            continue
                        level = len(m.group(1))
                        title = " ".join(m.group(2).strip().split())
                        if not title:
                            continue
                        out.append((level, title))
                    return out

                def _build_outline_tree(
                    headings: list[tuple[int, str]],
                    parent_chunk_indices: list[int],
                ) -> list[dict]:
                    nodes: list[dict] = []
                    for i, (level, title) in enumerate(headings):
                        if parent_chunk_indices:
                            mapped = parent_chunk_indices[i] if i < len(parent_chunk_indices) else parent_chunk_indices[-1]
                        else:
                            mapped = i

                        nodes.append(
                            {
                                "id": f"h-{i}",
                                "title": title,
                                "level": level,
                                "parent_chunk_index": int(mapped),
                                "children": [],
                            }
                        )

                    roots: list[dict] = []
                    stack: list[dict] = []
                    for n in nodes:
                        while stack and int(stack[-1].get("level") or 1) >= int(n.get("level") or 1):
                            stack.pop()
                        if stack:
                            stack[-1].setdefault("children", []).append(n)
                        else:
                            roots.append(n)
                        stack.append(n)
                    return roots

                extraction = (loaded.metadata or {}).get("extraction")
                headings = _extract_markdown_headings(cleaned)
                parent_chunk_indices = [int(p.index) for p in parent_chunks]
                outline_tree = _build_outline_tree(headings, parent_chunk_indices)

                row = db.query(DocumentOutline).filter(DocumentOutline.document_id == doc.id).first()
                if row:
                    row.extraction = extraction
                    row.outline_json = _json.dumps(outline_tree, ensure_ascii=False)
                else:
                    db.add(
                        DocumentOutline(
                            knowledge_base_id=int(doc.knowledge_base_id),
                            document_id=int(doc.id),
                            extraction=extraction,
                            outline_json=_json.dumps(outline_tree, ensure_ascii=False),
                        )
                    )
            except Exception as e:
                logger.warning("Failed to persist outline for doc %s: %s", doc.id, e)

            # Vectorize
            parent_texts = [p.content for p in parent_chunks]
            parent_embeddings = embedding_service.embed_texts(parent_texts) if parent_texts else []

            child_texts = [c.content for c in child_chunks]
            child_embeddings = embedding_service.embed_texts(child_texts) if child_texts else []

            parent_data = [(p.index, p.content, emb, p.metadata) for p, emb in zip(parent_chunks, parent_embeddings)]
            child_data = [
                (c.index, c.content, emb, c.metadata, int(c.parent_index) if c.parent_index is not None else 0)
                for c, emb in zip(child_chunks, child_embeddings)
            ]

            if parent_data or child_data:
                vector_store.store_hierarchical_vectors(doc.id, parent_data, child_data)

            doc.chunk_count = len(parent_chunks) + len(child_chunks)
            doc.status = "completed"
            db.commit()
            logger.info(
                "Processed doc %s (%s): %s parents + %s children",
                doc.id,
                doc.file_type,
                len(parent_chunks),
                len(child_chunks),
            )

        except Exception as e:
            logger.error("Error processing doc %s: %s", doc.id, e)
            doc.status = "failed"
            doc.error_message = str(e)
            db.commit()
        finally:
            try:
                if local_path and os.path.exists(local_path):
                    os.remove(local_path)
            except Exception:
                pass


async def rebuild_vectors(kb_id: int) -> None:
    """Rebuild vectors for all documents in a knowledge base."""
    from ..config import settings

    with MySQLSessionLocal() as db:
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
        if kb:
            kb.embedding_model = settings.embedding_model
            db.commit()

        docs = db.query(Document).filter(Document.knowledge_base_id == kb_id).all()
        doc_ids = [d.id for d in docs]

    # Process sequentially (can be parallelized later).
    for doc_id in doc_ids:
        await process_document(doc_id)


async def build_graph(kb_id: int) -> None:
    """Build knowledge graph for new documents in a KB."""
    from ..services.minio_service import minio_service
    from ..services.document_loader import document_loader
    from ..services.graph_builder import graph_builder
    from langchain_core.documents import Document as LangChainDocument

    with MySQLSessionLocal() as db:
        docs = db.query(Document).filter(
            Document.knowledge_base_id == kb_id,
            Document.graph_built == False,
        ).all()
        doc_infos = [{"id": d.id, "filename": d.filename, "file_path": d.file_path} for d in docs]

    if not doc_infos:
        return

    for doc_info in doc_infos:
        doc_id = doc_info["id"]
        filename = doc_info["filename"]
        file_path = doc_info["file_path"]
        temp_file: Optional[str] = None

        try:
            if not file_path:
                continue
            temp_file = minio_service.download_file(file_path)
            if not temp_file or not os.path.exists(temp_file):
                continue

            # Ensure loader sees a reasonable suffix.
            filename_for_loader = filename
            if not os.path.splitext(filename_for_loader)[1]:
                ext = os.path.splitext(file_path)[1]
                if ext:
                    filename_for_loader += ext

            loaded = document_loader.load(temp_file, filename_for_loader)
            content = loaded.content

            # Chunk (Graph extraction prefers larger chunks).
            doc_chunks = []
            chunk_size = 3000
            for i in range(0, len(content), chunk_size):
                chunk = content[i : i + chunk_size]
                if len(chunk.strip()) >= 20:
                    doc_chunks.append(
                        LangChainDocument(
                            page_content=chunk,
                            metadata={"source": filename, "kb_id": kb_id, "doc_id": doc_id, "chunk": i // chunk_size},
                        )
                    )

            if not doc_chunks:
                continue

            await graph_builder.build_from_documents(doc_chunks)

            with MySQLSessionLocal() as update_db:
                d = update_db.query(Document).filter(Document.id == doc_id).first()
                if d:
                    d.graph_built = True
                    update_db.commit()

        finally:
            try:
                if temp_file and os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass
