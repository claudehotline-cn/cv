from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from PyPDF2 import PdfReader
import requests
from bs4 import BeautifulSoup
import time
from urllib.parse import urljoin

from .config import get_settings


def fetch_url_with_images(url: str, max_images: int = 5, max_text_chars: int = 60000) -> Dict[str, Any]:
    """从 URL 获取正文文本与若干图片 URL。

    - 使用简单的 HTML 解析，从 <main>/<article>/<body> 中抽取文本；
    - 提取最多 max_images 张图片，并将相对路径转换为绝对 URL；
    - 文本长度截断到 max_text_chars，以控制后续 LLM 负载。
    """

    settings = get_settings()
    headers = {
        "User-Agent": settings.http_user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    }
    last_error: Exception | None = None
    attempts = max(1, int(settings.http_max_attempts or 1))
    timeout = float(settings.http_timeout_sec)
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(url, timeout=timeout, headers=headers)
            resp.raise_for_status()
            break
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_error = exc
            if attempt >= attempts:
                raise
            time.sleep(float(settings.http_retry_backoff_sec) * attempt)
        except Exception as exc:
            last_error = exc
            raise
    else:  # pragma: no cover
        raise last_error or RuntimeError("fetch_url_with_images: unknown error")

    html = resp.text

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    main = soup.find("main") or soup.find("article") or soup.body or soup
    texts: List[str] = []
    for string in main.stripped_strings:
        texts.append(string)

    text = "\n".join(texts)
    if len(text) > max_text_chars:
        text = text[:max_text_chars]

    images: List[Dict[str, Any]] = []
    for img in main.find_all("img", limit=max_images):
        src = img.get("src")
        if not src:
            continue
        full_url = urljoin(url, src)
        alt = img.get("alt") or ""
        # 同时提供 src 与 url 字段，兼容下游期望
        images.append({"src": full_url, "url": full_url, "alt": alt})

    return {"url": url, "title": title, "text": text, "images": images}


def load_text_from_file(path: str, max_text_chars: int = 60000) -> Dict[str, Any]:
    """从本地文件加载文本内容。

    当前支持：
      - .txt / .md：按 UTF-8 文本读取；
      - .pdf：使用 PyPDF2 读取所有页面文本；
    其它复杂格式暂不处理，返回空文本占位。
    """

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在：{path}")

    suffix = p.suffix.lower()
    text = ""
    if suffix in {".txt", ".md"}:
        text = p.read_text(encoding="utf-8", errors="ignore")
    elif suffix == ".pdf":
        reader = PdfReader(str(p))
        parts: List[str] = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        text = "\n".join(parts)
    else:
        text = ""

    if len(text) > max_text_chars:
        text = text[:max_text_chars]

    return {"path": str(p), "text": text, "images": []}


def load_uploaded_file_text(path: str, max_text_chars: int = 60000) -> str:
    """符合提示词约定的文件文本读取工具封装。

    返回文件文本字符串，用于 Deep Agent 的 load_uploaded_file_text 工具。
    """

    info = load_text_from_file(path=path, max_text_chars=max_text_chars)
    return info.get("text", "")


def extract_images_from_pdf(file_path: str, article_id: str) -> List[Dict[str, Any]]:
    """从 PDF 中提取图片的占位实现。

    当前版本暂未实现真实图片提取逻辑，返回空列表。
    保留该函数以符合 article_agent2 设计的工具接口。
    """

    _ = (file_path, article_id)
    return []


def extract_images_from_docx(file_path: str, article_id: str) -> List[Dict[str, Any]]:
    """从 DOCX 中提取图片的占位实现（暂未实现，返回空）。"""

    _ = (file_path, article_id)
    return []


def extract_images_from_pptx(file_path: str, article_id: str) -> List[Dict[str, Any]]:
    """从 PPTX 中提取图片的占位实现（暂未实现，返回空）。"""

    _ = (file_path, article_id)
    return []


def export_markdown(article_markdown: str, title: str, article_id: str) -> Dict[str, str]:
    """将最终 Markdown 落盘，并返回下载链接信息。

    函数签名与 article_agent2 设计保持一致：
      export_markdown(article_markdown: str, title: str, article_id: str) -> dict
    """

    settings = get_settings()
    base_dir = Path(settings.articles_base_dir)
    article_dir = base_dir / article_id
    article_dir.mkdir(parents=True, exist_ok=True)

    filename = "article.md"
    file_path = article_dir / filename
    file_path.write_text(article_markdown, encoding="utf-8")

    base_url = settings.articles_base_url.rstrip("/")
    md_url = f"{base_url}/{article_id}/{filename}"

    return {
        "article_id": article_id,
        "title": title,
        "md_path": str(file_path),
        "md_url": md_url,
    }


__all__ = [
    "fetch_url_with_images",
    "load_text_from_file",
    "load_uploaded_file_text",
    "extract_images_from_pdf",
    "extract_images_from_docx",
    "extract_images_from_pptx",
    "export_markdown",
]
