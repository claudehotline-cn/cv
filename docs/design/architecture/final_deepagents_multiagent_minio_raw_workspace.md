# 最终版：LangChain 1.0 + Deep Agents 多 Agent 内容整理与写作系统  
（原始文档存 MinIO；中间产物存 Deep Agents FilesystemBackend 工作区；按 `article_id` 分区）

> 适用场景：用户提供 **URL + 上传文件（PDF 等）** → 自动整理成“可追溯证据”的研究笔记 → 分章节写作 → 审阅 → 插图定位 → 组装成最终文档（MD/DOCX/PDF）。

---

## 0. 你当前的约束与目标

### 0.1 你确认的存储边界
- **原始文档（raw）**：统一上传到 **MinIO**（S3 兼容对象存储）。
- **中间产物（corpus / plans / research / draft / review / assets / output）**：写到 Deep Agents 的 **FilesystemBackend 工作区**（磁盘/volume），按 `article_id` 分区。  
  Deep Agents 支持可插拔文件系统 backend，并可用 `FilesystemBackend(root_dir=...)` 将文件工具读写落到指定目录。 citeturn0search0turn0search14turn0search3

### 0.2 你已有的 Agent 流水线
- Planner：基于抓取内容生成大纲
- Research：按大纲整理资料，输出 `research_note.json`
- Writer：按 `research_note.json` 分章节写作
- Reviewer：按大纲审阅（通过后继续）
- Illustrator：分析图片内容并精确定位插图位置
- Assemble：组装最终文档

> 本方案会在前面补一个 **Ingest Agent**（只负责 I/O 重活：下载/解析/结构化/落盘），让 Planner 专注“规划”。这能显著降低上下文爆炸与失败率。Deep Agents 官方也强调：文件系统工具可用来将大结果 offload，避免上下文溢出。 citeturn0search3

---

## 1. 整体架构与数据流

```mermaid
flowchart TD
  U[User: article_id + sources(URL/MinIO)] --> CH[Chief/Orchestrator]
  CH --> ING[Ingest Agent]
  ING --> WS[(FilesystemBackend Workspace)]
  CH --> PL[Planner Agent]
  PL --> WS
  CH --> RE[Research Agent]
  RE --> WS
  CH --> WR[Writer Agent]
  WR --> WS
  CH --> RV[Reviewer Agent]
  RV --> WS
  CH --> IL[Illustrator Agent]
  IL --> WS
  CH --> AS[Assemble Agent]
  AS --> WS
  ING <-->|read raw| M[(MinIO raw bucket)]
```

### 1.1 为什么要“落盘驱动”
Deep Agents 的文件系统工具（`ls/read_file/write_file/edit_file` 等）允许把**解析全文、表格、图片 OCR 结果**等大内容写入工作区，从而避免上下文窗口溢出，并支持可复现与增量更新。 citeturn0search3turn0search14

---

## 2. 命名与分区：article_id / doc_id / chunk_id

### 2.1 ID 约定（强烈建议定死）
- `article_id`：一次“生成最终文章”的业务 ID（= task_id）。**工作区分区**的主键。
- `doc_id`：一个输入源（一个 URL / 一个 PDF）的文档 ID。建议：  
  - MinIO：用 `{bucket}:{key}:{etag}:{size}` 计算 hash  
  - URL：用 `sha256(url + fetched_at + content_hash)` 或 `sha256(canonical_url + content_hash)`
- `chunk_id`：用于检索与引用的最小片段 ID（稳定、可追溯）
- `element_id`：元素级 ID（表/图/公式/代码块）用于插图/表格精准定位

---

## 3. 存储设计

## 3.1 MinIO：只存 raw（原始文档）

**推荐 key：**
```text
raw/{tenant}/{article_id}/{upload_id}/{filename}
```

**MinIO SDK 注意事项：**  
`get_object()` 返回响应需要在使用后关闭；如需复用连接，还需要显式调用 `response.release_conn()`。 citeturn0search2

---

## 3.2 Workspace（FilesystemBackend）：按 article_id 分区的目录结构

设定 `FilesystemBackend(root_dir=/workspace)`，则建议：

```text
/workspace/articles/{article_id}/
  corpus/
    {doc_id}/
      parsed/
        full.md
        elements.jsonl
      chunks.jsonl
      manifest.json
      ingest_report.json

  plans/
    outline.json
    section_plan.json
    open_questions.json

  research/
    research_note.json

  draft/
    draft.md
    citations_map.json

  review/
    review_report.json

  assets/
    illustration_plan.json
    figures/

  output/
    final.md
    final.docx
    final.pdf
    build_log.json
```

> 说明：你之前说“corpus 也想按 article_id 分”，本方案就是用 `articles/{article_id}/corpus/...` 做分区。

---

## 4. 核心概念：chunk 是什么、为什么需要

**Chunk** = 把“长文档”切成多个可检索、可引用的小片段（每个片段带 metadata）。  
LangChain 官方文档解释了 `chunk_size`、`chunk_overlap` 等参数；重叠（overlap）能缓解切分造成的信息丢失。 citeturn1search1turn1search2

### 4.1 chunk 与 full.md / elements 的关系
- `full.md`：通读友好（给人看/快速浏览）
- `elements.jsonl`：最精确（Text/Table/Image/Formula/Code…，带页码/坐标/ID）
- `chunks.jsonl`：检索友好（Research/Writer/Reviewer 主要消费）

> Illustrator 主要读 `elements.jsonl`（图像/表格元素），Research 主要检索 `chunks.jsonl`。

---

## 5. 子 Agent 职责、输入、输出、落盘（竖版）

### 5.1 Ingest Agent（采集/解析/落盘）
| 字段 | 内容 |
|---|---|
| 核心职责 | 1) 从 URL 或 MinIO 拉取原始内容（bytes） 2) 类型识别（HTML/PDF…）3) 解析为 `full.md` + `elements` 4) chunking 5) 写 `manifest/ingest_report` |
| 输入 | `article_id` + `sources[]`（URL 或 MinIORef） + `ingest_options` |
| 输出（回传） | `IngestReport[]`（doc_id、summary、headings、manifest_path、quality_flags） |
| 落盘 | `/workspace/articles/{article_id}/corpus/{doc_id}/...` |

### 5.2 Planner Agent（大纲与证据需求）
| 字段 | 内容 |
|---|---|
| 核心职责 | 只读 `manifest.json` 的摘要/标题结构/统计，生成：大纲 + 章节证据需求（section_plan）+ 缺口 |
| 输入 | `article_id` + `manifest_paths[]` + 用户写作需求 |
| 输出（回传） | `outline.json`、`section_plan.json`、`open_questions.json` |
| 落盘 | `/workspace/articles/{article_id}/plans/*` |

### 5.3 Research Agent（按大纲整理证据）
| 字段 | 内容 |
|---|---|
| 核心职责 | 按 `section_plan` 检索 `chunks/elements`，把每章要点与证据整理成 `research_note.json` |
| 输入 | `outline.json` + `section_plan.json` + `chunks/elements` |
| 输出（回传） | `research_note.json`（每条结论都带 chunk_id/element_id） |
| 落盘 | `/workspace/articles/{article_id}/research/research_note.json` |

### 5.4 Writer Agent（分章节写作）
| 字段 | 内容 |
|---|---|
| 核心职责 | 只用 `research_note.json` 写作；正文中保留引用锚点（chunk_id/element_id） |
| 输入 | `research_note.json` + 写作风格/模板 |
| 输出（回传） | `draft.md` + `citations_map.json` |
| 落盘 | `/workspace/articles/{article_id}/draft/*` |

### 5.5 Reviewer Agent（对照大纲 Gate）
| 字段 | 内容 |
|---|---|
| 核心职责 | 对照大纲检查：覆盖度、结构一致性、证据充分性、可读性；pass/fail + 修改清单 |
| 输入 | `outline.json` + `draft.md` + `citations_map.json` |
| 输出（回传） | `review_report.json` |
| 落盘 | `/workspace/articles/{article_id}/review/review_report.json` |

### 5.6 Illustrator Agent（图片理解 + 精确插图定位）
| 字段 | 内容 |
|---|---|
| 核心职责 | 读 `elements.jsonl` 里的图/表元素，生成图注与插入锚点；必要时裁剪/重命名图像资源 |
| 输入 | `draft.md` + `elements.jsonl`（Image/Table/…） |
| 输出（回传） | `illustration_plan.json`（figure_id → anchor → caption → source） |
| 落盘 | `/workspace/articles/{article_id}/assets/*` |

### 5.7 Assemble Agent（组装最终交付物）
| 字段 | 内容 |
|---|---|
| 核心职责 | 合并 draft + 插图计划 + 引用映射，输出 final.*；写 build_log |
| 输入 | `draft.md` + `illustration_plan.json` + `citations_map.json` |
| 输出（回传） | `final.md/docx/pdf` + `build_log.json` |
| 落盘 | `/workspace/articles/{article_id}/output/*` |

---

## 6. 解析与结构化：HTML / PDF（bytes）能力建议

### 6.1 HTML（URL）
- 抓取：requests/httpx
- 提取：你当前用的 trafilatura（保留表格/格式）完全可以继续用
- 再结构化：根据标题/分隔符切块，写入 chunks

### 6.2 PDF（MinIO bytes）
**优先推荐 Docling：**其 PyPI 文档给出了“从二进制 PDF 流（BytesIO）转换”的示例。 citeturn0search1turn0search5

---

## 7. 关键 JSON 契约（最小可用版）

### 7.1 manifest.json（Ingest → Planner/Research/Illustrator）
```json
{
  "doc_id": "doc_xxx",
  "article_id": "{article_id}",
  "source_ref": {
    "type": "minio|url",
    "bucket": "raw-docs",
    "key": "raw/acme/{article_id}/upload_xxx/paper.pdf",
    "etag": "....",
    "size": 1234567,
    "content_type": "application/pdf"
  },
  "paths": {
    "full_md": "articles/{article_id}/corpus/doc_xxx/parsed/full.md",
    "elements": "articles/{article_id}/corpus/doc_xxx/parsed/elements.jsonl",
    "chunks": "articles/{article_id}/corpus/doc_xxx/chunks.jsonl"
  },
  "headings": ["1 引言", "2 方法", "3 实验"],
  "stats": {"pages": 12, "chunks": 84, "tables": 3, "images": 9},
  "quality_flags": []
}
```

### 7.2 outline.json（Planner → Research/Reviewer）
```json
{
  "article_id": "{article_id}",
  "title": "文章标题",
  "sections": [
    {"id":"s1","title":"背景与问题定义","goals":["..."],"key_questions":["..."]},
    {"id":"s2","title":"核心方法","goals":["..."],"key_questions":["..."]}
  ]
}
```

### 7.3 section_plan.json（Planner → Research）
```json
{
  "article_id": "{article_id}",
  "sections": [
    {
      "section_id":"s2",
      "required_evidence": [
        {"type":"definition","min":2},
        {"type":"table","min":1},
        {"type":"figure","min":1}
      ],
      "preferred_sources": ["doc_xxx","doc_yyy"]
    }
  ]
}
```

### 7.4 research_note.json（Research → Writer/Reviewer/Illustrator）
```json
{
  "article_id": "{article_id}",
  "sections": [
    {
      "section_id":"s2",
      "bullet_points":["...","..."],
      "evidence": [
        {
          "claim":"方法A的关键步骤是...",
          "refs":[
            {"doc_id":"doc_xxx","chunk_id":"doc_xxx_p03_c07","page":3},
            {"doc_id":"doc_xxx","element_id":"eq_5","page":3}
          ]
        }
      ]
    }
  ]
}
```

### 7.5 citations_map.json（Writer → Reviewer/Assemble）
```json
{
  "anchors": [
    {
      "anchor":"cite:doc_xxx_p03_c07",
      "refs":[{"doc_id":"doc_xxx","chunk_id":"doc_xxx_p03_c07","page":3}]
    }
  ]
}
```

### 7.6 illustration_plan.json（Illustrator → Assemble）
```json
{
  "figures": [
    {
      "figure_id":"fig_2",
      "source": {"doc_id":"doc_xxx","element_id":"img_12","page":5},
      "caption":"图2：……",
      "insert_after_anchor":"## 核心方法",
      "layout": {"width":"70%","align":"center"}
    }
  ]
}
```

---

## 8. 实现示例（关键代码骨架）

### 8.1 MinIO 读取 raw bytes（必做：close + release_conn）
```python
from minio import Minio

def load_bytes_from_minio(client: Minio, bucket: str, key: str, version_id: str | None = None) -> bytes:
    resp = None
    try:
        resp = client.get_object(bucket, key, version_id=version_id)
        return resp.read()
    finally:
        if resp is not None:
            resp.close()
            resp.release_conn()
```
> `get_object()` 的响应需要关闭，并建议显式 `release_conn()` 以复用连接。 citeturn0search2

### 8.2 PDF bytes → Docling（BytesIO 直转）
Docling PyPI 给了“Convert from binary PDF streams”的示例。 citeturn0search1turn0search5

```python
from io import BytesIO
from docling.datamodel.base_models import DocumentStream
from docling.document_converter import DocumentConverter
from docling.datamodel.document_conversion_input import DocumentConversionInput

def pdf_bytes_to_docling_markdown(pdf_bytes: bytes, filename: str = "doc.pdf") -> str:
    buf = BytesIO(pdf_bytes)
    docs = [DocumentStream(filename=filename, stream=buf)]
    conv_input = DocumentConversionInput.from_streams(docs)
    results = DocumentConverter().convert(conv_input)
    doc = results[0].document
    return doc.export_to_markdown()
```

### 8.3 Chunking（RecursiveCharacterTextSplitter）
LangChain 官方文档说明了 `chunk_size` 与 `chunk_overlap` 的含义，并建议多数场景从 `RecursiveCharacterTextSplitter` 开始。 citeturn1search1turn1search2

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

def chunk_text(text: str, *, chunk_size: int = 1200, chunk_overlap: int = 200):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
    )
    return splitter.split_text(text)
```

### 8.4 Deep Agents 组装（主 agent + FilesystemBackend + subagents）
Deep Agents 支持通过 `FilesystemBackend(root_dir=...)` 指定文件工具落盘位置。 citeturn0search0turn0search3turn0search14

```python
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

agent = create_deep_agent(
    backend=FilesystemBackend(root_dir="/workspace"),
    system_prompt=(
        "You are the chief editor. "
        "All intermediate artifacts must be written under /workspace/articles/{article_id}/... "
        "Delegate to subagents via task()."
    ),
    subagents=[
        {"name":"ingest","description":"Fetch raw from URL/MinIO and build corpus","system_prompt":"..."},
        {"name":"planner","description":"Generate outline and section plan","system_prompt":"..."},
        {"name":"research","description":"Collect evidence per section","system_prompt":"..."},
        {"name":"writer","description":"Write sections using research_note","system_prompt":"..."},
        {"name":"reviewer","description":"Review draft against outline","system_prompt":"..."},
        {"name":"illustrator","description":"Figure captions and placements","system_prompt":"..."},
        {"name":"assembler","description":"Assemble final output","system_prompt":"..."},
    ],
)
```

---

## 9. 端到端运行示例（可直接做 demo）

### 9.1 输入（Chief agent 接收）
```json
{
  "article_id": "article_123",
  "sources": [
    {"type":"url","url":"https://example.com/a.html"},
    {
      "type":"minio",
      "bucket":"raw-docs",
      "key":"raw/acme/article_123/8f0b/paper.pdf",
      "content_type":"application/pdf"
    }
  ],
  "requirements": {
    "language":"zh",
    "style":"技术长文",
    "length":"3000-5000字",
    "need_images": true
  }
}
```

### 9.2 期望产物（全部在 workspace）
- `/workspace/articles/article_123/corpus/...`
- `/workspace/articles/article_123/plans/outline.json`
- `/workspace/articles/article_123/research/research_note.json`
- `/workspace/articles/article_123/draft/draft.md`
- `/workspace/articles/article_123/review/review_report.json`
- `/workspace/articles/article_123/assets/illustration_plan.json`
- `/workspace/articles/article_123/output/final.md`

---

## 10. 工程化建议（少走弯路）

1. **严格分层**：Ingest 做重解析；Planner 不碰重解析；Writer 不碰检索（只读 research_note）。
2. **证据链强约束**：Writer/Reviewer 只认可 `chunk_id/element_id` 的 refs。
3. **chunk 参数先用默认推荐**：多数场景从 RecursiveCharacterTextSplitter 开始，再按文档类型调整。 citeturn1search2
4. **MinIO 只当 raw 真相源**：中间产物在 workspace，便于迭代与清理；必要时再把 final.* 上传到对象存储给用户下载。

---

## 11. 参考资料（放在代码块里，便于复制）

```text
Deep Agents overview (file system tools, write_todos, context offload):
- https://docs.langchain.com/oss/python/deepagents/overview

Deep Agents backends (FilesystemBackend, routing, virtual FS):
- https://docs.langchain.com/oss/python/deepagents/backends

deepagents GitHub README (FilesystemBackend(root_dir=...)):
- https://github.com/langchain-ai/deepagents

Docling (PyPI) - Convert from binary PDF streams:
- https://pypi.org/project/docling/

MinIO Python SDK API - get_object close + release_conn:
- https://docs.min.io/enterprise/aistor-object-store/developers/sdk/python/api/

LangChain recursive text splitter (chunk_size, chunk_overlap):
- https://docs.langchain.com/oss/python/integrations/splitters/recursive_text_splitter
- https://docs.langchain.com/oss/python/integrations/splitters
```

---

文档生成时间：2026-01-02 17:40:59
