from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from PyPDF2 import PdfReader
import requests
from bs4 import BeautifulSoup
import time
from urllib.parse import urljoin

from .config import get_settings


def fetch_url_with_images(url: str, max_images: int = 5, max_text_chars: int = 60000) -> Dict[str, Any]:
    """从 URL 获取正文文本与若干图片 URL。

    抓取策略（按优先级）：
    1. 使用 trafilatura 提取正文（高质量，去除噪音）；
    2. 若 trafilatura 失败或返回空，回退到 BeautifulSoup；
    3. 若启用 Playwright 且上述结果为空，使用 Playwright 渲染后重试。
    """

    settings = get_settings()
    headers = {
        "User-Agent": settings.http_user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    }

    # Step 1: 使用 requests 获取 HTML
    html = _fetch_html_with_requests(url, headers, settings)

    # Step 2: 提取正文和图片
    result = _extract_content(html, url, max_images, max_text_chars, settings)

    # Step 3: 若正文为空且启用了 Playwright，尝试 JS 渲染
    if not result.get("text") and settings.enable_playwright_fetch:
        try:
            html = _fetch_html_with_playwright(url, settings.playwright_timeout_sec)
            result = _extract_content(html, url, max_images, max_text_chars, settings)
        except Exception as exc:
            _LOGGER.warning("playwright_fetch_failed url=%s error=%s", url, exc)

    return result


def _fetch_html_with_requests(url: str, headers: Dict[str, str], settings: Any) -> str:
    """使用 requests 获取 HTML 内容。"""
    last_error: Exception | None = None
    attempts = max(1, int(settings.http_max_attempts or 1))
    timeout = float(settings.http_timeout_sec)

    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(url, timeout=timeout, headers=headers)
            resp.raise_for_status()
            return resp.text
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_error = exc
            if attempt >= attempts:
                raise
            time.sleep(float(settings.http_retry_backoff_sec) * attempt)
        except Exception as exc:
            last_error = exc
            raise

    raise last_error or RuntimeError("fetch_url: unknown error")


def _extract_content(html: str, url: str, max_images: int, max_text_chars: int, settings: Any) -> Dict[str, Any]:
    """从 HTML 中提取正文与图片。

    优先使用 trafilatura 统一提取文本和图片（确保来自同一"主内容区域"），
    若 trafilatura 失败或图片为空，则用 BeautifulSoup 兜底。
    """

    soup = BeautifulSoup(html, "html.parser")

    # 提取标题
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    text = ""
    images: List[Dict[str, Any]] = []

    # Step A: 尝试使用 trafilatura 统一提取正文和图片
    if settings.use_trafilatura:
        text, images = _extract_with_trafilatura(html, url, max_images)

    # Step B: 文本回退到 BeautifulSoup
    if not text:
        text = _extract_with_beautifulsoup(soup, url)

    # Step C: 图片回退到 BeautifulSoup（若 trafilatura 没抓到图片）
    if not images:
        images = _extract_images_from_soup(soup, url, max_images)

    if len(text) > max_text_chars:
        text = text[:max_text_chars]

    return {"url": url, "title": title, "text": text, "images": images}


def _extract_surrounding_text(full_text: str, img_position: int, context_chars: int = 200) -> str:
    """提取图片周围的文本作为上下文。
    
    Args:
        full_text: 完整的Markdown文本
        img_position: 图片在文本中的位置（match.start()）
        context_chars: 前后各提取多少字符
        
    Returns:
        周围文本上下文
    """
    start = max(0, img_position - context_chars)
    end = min(len(full_text), img_position + context_chars)
    context = full_text[start:end].strip()
    # 清理Markdown图片语法本身
    import re
    context = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', '', context)
    return context.strip()


def _extract_with_trafilatura(html: str, url: str, max_images: int) -> Tuple[str, List[Dict[str, Any]]]:
    """使用 trafilatura 统一提取正文和图片（高质量）。

    返回 (text, images)，其中 images 从 Markdown 输出中解析。
    """
    try:
        import trafilatura
        import re

        # 使用 trafilatura 提取，开启图片以便解析
        result = trafilatura.extract(
            html,
            url=url,
            include_tables=True,
            include_images=True,  # 开启图片提取
            include_links=False,
            output_format="markdown",
            favor_precision=True,
        )

        if not result:
            return "", []

        text = result.strip()

        # 解析 Markdown 图片语法 ![alt](url) 并收集周围文本
        images: List[Dict[str, Any]] = []
        img_pattern = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
        for match in img_pattern.finditer(text):
            alt = match.group(1) or ""
            img_url = match.group(2) or ""
            if not img_url:
                continue
            # 过滤小图标和 data URI
            if img_url.startswith("data:") or "icon" in img_url.lower() or "logo" in img_url.lower():
                continue
            # 转换为绝对 URL
            full_url = urljoin(url, img_url)
            
            # 提取图片周围文本作为上下文
            surrounding_context = _extract_surrounding_text(text, match.start(), context_chars=200)
            
            images.append({
                "src": full_url,
                "url": full_url,
                "alt": alt,
                "context": surrounding_context,  # 新增：周围文本上下文
            })
            if len(images) >= max_images:
                break

        return text, images

    except ImportError:
        _LOGGER.warning("trafilatura not installed, skipping")
        return "", []
    except Exception as exc:
        _LOGGER.warning("trafilatura_extract_failed url=%s error=%s", url, exc)
        return "", []


def _extract_with_beautifulsoup(soup: BeautifulSoup, url: str) -> str:
    """使用 BeautifulSoup 提取正文（回退方案）。"""
    from urllib.parse import urlparse

    # 移除无用标签
    for tag in soup(["script", "style", "noscript", "nav", "footer", "aside"]):
        tag.decompose()

    # 针对 Wikipedia 的特化清理
    domain = urlparse(url).netloc.lower()
    if "wikipedia.org" in domain:
        for selector in ["#mw-panel", ".mw-editsection", ".reference", ".reflist", ".navbox", ".sistersitebox"]:
            for el in soup.select(selector):
                el.decompose()

    main = soup.find("main") or soup.find("article") or soup.body or soup
    texts: List[str] = []
    for string in main.stripped_strings:
        texts.append(string)

    return "\n".join(texts)


def _extract_images_from_soup(soup: BeautifulSoup, url: str, max_images: int) -> List[Dict[str, Any]]:
    """从 HTML 中提取图片 URL 和丰富的上下文信息。
    
    上下文优先级：
    1. figcaption - 最准确的图片说明
    2. 所在章节的标题 - 判断图片的主题领域
    3. alt 文本 - 通常是手动编写的描述
    4. 周围文本 - fallback
    """
    from urllib.parse import urlparse
    
    domain = urlparse(url).netloc.lower()
    is_wikipedia = "wikipedia.org" in domain
    
    main = soup.find("main") or soup.find("article") or soup.body or soup
    images: List[Dict[str, Any]] = []
    seen_urls: set = set()  # 避免重复图片
    
    # Wikipedia 特殊处理：优先从 infobox 和 thumbinner 中提取高质量图片
    if is_wikipedia:
        # 1. 从 infobox 中提取主图
        infobox = soup.find("table", class_="infobox")
        if infobox:
            for img in infobox.find_all("img", limit=3):
                img_data = _process_wikipedia_image(img, url, seen_urls)
                if img_data:
                    images.append(img_data)
        
        # 2. 从 thumbinner (带说明的图片) 中提取
        for thumb in soup.find_all("div", class_="thumbinner", limit=max_images * 2):
            img = thumb.find("img")
            if img:
                img_data = _process_wikipedia_image(img, url, seen_urls, thumb)
                if img_data:
                    images.append(img_data)
                    if len(images) >= max_images:
                        break
        
        # 3. 从正文中提取其他图片
        content = soup.find("div", id="mw-content-text") or main
        for img in content.find_all("img", limit=max_images * 3):
            if len(images) >= max_images:
                break
            img_data = _process_wikipedia_image(img, url, seen_urls)
            if img_data:
                images.append(img_data)
    
    # 通用图片提取（非 Wikipedia 或 Wikipedia 图片不足时的补充）
    if len(images) < max_images:
        for img in main.find_all("img", limit=max_images * 2):
            src = img.get("src") or img.get("data-src")
            if not src:
                continue
            
            # 过滤小图标和 base64 图片
            if src.startswith("data:"):
                continue
            src_lower = src.lower()
            if "icon" in src_lower or "logo" in src_lower or "button" in src_lower:
                continue
            if "1x1" in src_lower or "pixel" in src_lower:
                continue
            
            full_url = urljoin(url, src)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            
            alt = (img.get("alt") or "").strip()
            
            # 获取上下文信息
            figcaption_text = ""
            figure = img.find_parent("figure")
            if figure:
                figcaption = figure.find("figcaption")
                if figcaption:
                    figcaption_text = figcaption.get_text(strip=True)
            
            section_heading = ""
            parent = img.parent
            for _ in range(10):
                if parent is None:
                    break
                prev_heading = parent.find_previous(["h1", "h2", "h3", "h4"])
                if prev_heading:
                    section_heading = prev_heading.get_text(strip=True)
                    break
                parent = parent.parent
            
            context_parts = []
            if figcaption_text:
                context_parts.append(f"图注: {figcaption_text}")
            if section_heading:
                context_parts.append(f"章节: {section_heading}")
            if alt and len(alt) > 5:
                context_parts.append(f"描述: {alt}")
            
            context = "; ".join(context_parts) if context_parts else alt or "无上下文"
            
            images.append({
                "src": full_url,
                "url": full_url,
                "alt": alt,
                "figcaption": figcaption_text,
                "section_heading": section_heading,
                "context": context,
            })
            if len(images) >= max_images:
                break

    return images


def _process_wikipedia_image(img, base_url: str, seen_urls: set, container=None) -> Optional[Dict[str, Any]]:
    """处理 Wikipedia 图片，返回图片信息字典或 None。"""
    src = img.get("src") or img.get("data-src")
    if not src:
        return None
    
    # Wikipedia 图片过滤规则
    src_lower = src.lower()
    # 过滤 UI 图标和小图片
    if any(x in src_lower for x in ["icon", "logo", "button", "arrow", "ambox", "edit", "lock"]):
        return None
    if "1x1" in src_lower or "pixel" in src_lower:
        return None
    # 过滤 base64 和过小的图片
    if src.startswith("data:"):
        return None
    
    # 获取图片尺寸，过滤小于 100px 的图片
    width = img.get("width") or img.get("data-file-width")
    height = img.get("height") or img.get("data-file-height")
    try:
        if width and int(width) < 100:
            return None
        if height and int(height) < 100:
            return None
    except (ValueError, TypeError):
        pass
    
    # 转换为完整 URL
    full_url = urljoin(base_url, src)
    
    # 尝试获取更高清的 Wikipedia 图片
    # Wikipedia 缩略图 URL 示例: //upload.wikimedia.org/wikipedia/commons/thumb/xxx/220px-xxx.png
    # 尝试获取原图或更大的版本
    if "upload.wikimedia.org" in full_url and "/thumb/" in full_url:
        # 获取更大尺寸的图片 (800px)
        parts = full_url.rsplit("/", 1)
        if len(parts) == 2 and "px-" in parts[1]:
            # 替换尺寸为 800px
            import re
            larger_url = re.sub(r'\d+px-', '800px-', full_url)
            full_url = larger_url
    
    if full_url in seen_urls:
        return None
    seen_urls.add(full_url)
    
    alt = (img.get("alt") or "").strip()
    
    # 获取 figcaption（Wikipedia 使用 thumbcaption）
    figcaption_text = ""
    if container:
        caption_div = container.find("div", class_="thumbcaption")
        if caption_div:
            figcaption_text = caption_div.get_text(strip=True)
    
    # 尝试从 figure 获取
    if not figcaption_text:
        figure = img.find_parent("figure")
        if figure:
            figcaption = figure.find("figcaption")
            if figcaption:
                figcaption_text = figcaption.get_text(strip=True)
    
    # 获取所在章节标题
    section_heading = ""
    parent = img.parent
    for _ in range(15):
        if parent is None:
            break
        prev_heading = parent.find_previous(["h1", "h2", "h3", "h4"])
        if prev_heading:
            section_heading = prev_heading.get_text(strip=True)
            break
        parent = parent.parent
    
    context_parts = []
    if figcaption_text:
        context_parts.append(f"图注: {figcaption_text}")
    if section_heading:
        context_parts.append(f"章节: {section_heading}")
    if alt and len(alt) > 5:
        context_parts.append(f"描述: {alt}")
    
    context = "; ".join(context_parts) if context_parts else alt or "无上下文"
    
    return {
        "src": full_url,
        "url": full_url,
        "alt": alt,
        "figcaption": figcaption_text,
        "section_heading": section_heading,
        "context": context,
    }



def _fetch_html_with_playwright(url: str, timeout_sec: int) -> str:
    """使用 Playwright 渲染页面并获取 HTML（用于 JS 重站点）。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _LOGGER.warning("playwright not installed, skipping JS rendering")
        return ""

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=timeout_sec * 1000, wait_until="networkidle")
            html = page.content()
            browser.close()
            return html
    except Exception as exc:
        _LOGGER.warning("playwright_render_failed url=%s error=%s", url, exc)
        return ""


# 日志记录器
import logging
_LOGGER = logging.getLogger("article_agent.tools_files")


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
