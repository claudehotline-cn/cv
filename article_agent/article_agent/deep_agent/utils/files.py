from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from PyPDF2 import PdfReader
import requests
from bs4 import BeautifulSoup
import time
from urllib.parse import urljoin

from ...config.config import get_settings


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
    from urllib.parse import urlparse

    soup = BeautifulSoup(html, "html.parser")

    # 提取标题
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    text = ""
    images: List[Dict[str, Any]] = []
    extracted_formulas = []  # 存储提取的数学公式
    
    # 预处理：将 Wikipedia 数学公式转换为 LaTeX 格式
    # 这样 trafilatura 也能保留公式
    domain = urlparse(url).netloc.lower()
    if "wikipedia.org" in domain:
        original_len = len(html)
        html, extracted_formulas = _preprocess_wikipedia_math(html)
        _LOGGER.info(f"Wikipedia math preprocessing: url={url}, formulas_found={len(extracted_formulas)}, html_len_change={len(html)-original_len}")

    # Step A: 尝试使用 trafilatura 统一提取正文和图片
    if settings.use_trafilatura:
        text, images = _extract_with_trafilatura(html, url, max_images)

    # Step B: 文本回退到 BeautifulSoup
    if not text:
        text = _extract_with_beautifulsoup(soup, url)

    # Step C: 图片回退到 BeautifulSoup（若 trafilatura 没抓到图片）
    if not images:
        images = _extract_images_from_soup(soup, url, max_images)
    
    # Step D: 恢复数学公式（将占位符替换为实际公式）
    if extracted_formulas:
        import re
        restored_count = 0
        for i, (formula, is_block) in enumerate(extracted_formulas):
            placeholder = f'MATHFORMULA{i}ENDMATH'
            # 检查占位符是否在文本中（可能被 trafilatura 保留或丢弃）
            if placeholder in text:
                # 使用 Wikipedia 的 display 属性判断，或回退到启发式规则
                use_block = is_block or len(formula) > 60 or '\\sum' in formula or '\\frac' in formula or '\\int' in formula
                if use_block:
                    text = text.replace(placeholder, f'\n\n$${formula}$$\n\n')
                else:
                    text = text.replace(placeholder, f'${formula}$')
                restored_count += 1
        
        if restored_count > 0:
            _LOGGER.info(f"Restored {restored_count} formulas inline with text")
        
        # 如果公式全被丢弃，在文开头追加重要公式（确保 Researcher 能看到）
        if '$$' not in text and '$' not in text and extracted_formulas:
            important_formulas = [(f, b) for f, b in extracted_formulas if len(f) > 20]
            if important_formulas:
                formula_section = "## 核心数学公式\n\n" + "\n\n".join([f'$${f}$$' for f, _ in important_formulas[:10]]) + "\n\n---\n\n"
                text = formula_section + text  # 放到开头而不是末尾
                _LOGGER.info(f"Prepended {min(len(important_formulas), 10)} important formulas to text")

    # 不再截断：数据存到文件，不直接传给 LLM
    # Researcher 读取时自行控制传给 LLM 的长度

    return {"url": url, "title": title, "text": text, "images": images}


def _preprocess_wikipedia_math(html: str) -> Tuple[str, List[Tuple[str, bool]]]:
    """预处理 Wikipedia HTML，将 <math> 标签中的 LaTeX 公式提取出来。
    
    Wikipedia 使用 MathML 格式，LaTeX 源码存储在 <annotation encoding="application/x-tex"> 中。
    将 <math> 标签替换为占位符格式，同时收集所有公式以便后续使用。
    
    Returns:
        Tuple[str, List[Tuple[str, bool]]]: (处理后的HTML, [(公式, 是否块级)]列表)
    """
    import re
    
    extracted_formulas = []  # [(latex_str, is_block), ...]
    
    # 匹配 <math>...</math> 标签，提取 annotation 中的 LaTeX
    def replace_math(match):
        math_content = match.group(0)
        
        # 检查 display 属性判断是 inline 还是 block
        display_match = re.search(r'display="([^"]+)"', math_content, re.IGNORECASE)
        is_block = display_match and display_match.group(1).lower() == 'block'
        
        # 尝试提取 annotation encoding="application/x-tex" 内容
        annotation_match = re.search(
            r'<annotation[^>]*encoding="application/x-tex"[^>]*>([^<]+)</annotation>',
            math_content
        )
        if annotation_match:
            latex = annotation_match.group(1).strip()
            extracted_formulas.append((latex, is_block))
            # 使用文本格式占位符，trafilatura 不会过滤
            return f' MATHFORMULA{len(extracted_formulas)-1}ENDMATH '
        # 回退：尝试 alttext 属性
        alttext_match = re.search(r'alttext="([^"]+)"', math_content)
        if alttext_match:
            latex = alttext_match.group(1).strip()
            extracted_formulas.append((latex, is_block))
            return f' MATHFORMULA{len(extracted_formulas)-1}ENDMATH '
        return ''
    
    # 替换所有 <math>...</math> 标签
    html = re.sub(r'<math[^>]*>.*?</math>', replace_math, html, flags=re.DOTALL | re.IGNORECASE)
    
    # 同时处理代码块 <pre><code>...</code></pre> -> ```...```
    html = _preprocess_code_blocks(html)
    
    return html, extracted_formulas


def _preprocess_code_blocks(html: str) -> str:
    """预处理 HTML，将 <pre><code> 代码块转换为 Markdown 代码块格式。
    
    支持的格式：
    - <pre><code class="language-python">...</code></pre>
    - <pre class="code">...</pre>
    - <code>...</code>（内联代码）
    """
    import re
    from html import unescape
    
    # 1. 处理 <pre><code>...</code></pre> 块
    def replace_pre_code(match):
        full_match = match.group(0)
        # 尝试提取语言
        lang_match = re.search(r'class="[^"]*(?:language-|lang-)(\w+)', full_match, re.IGNORECASE)
        lang = lang_match.group(1) if lang_match else ''
        
        # 提取 <code> 内容
        code_match = re.search(r'<code[^>]*>(.*?)</code>', full_match, re.DOTALL | re.IGNORECASE)
        if code_match:
            code_content = code_match.group(1)
        else:
            # 直接从 <pre> 提取
            pre_match = re.search(r'<pre[^>]*>(.*?)</pre>', full_match, re.DOTALL | re.IGNORECASE)
            code_content = pre_match.group(1) if pre_match else ''
        
        # 移除内部 HTML 标签，保留文本
        code_content = re.sub(r'<[^>]+>', '', code_content)
        code_content = unescape(code_content).strip()
        
        if code_content:
            return f'\n\n```{lang}\n{code_content}\n```\n\n'
        return ''
    
    # 匹配 <pre>...</pre>（可能包含 <code>）
    html = re.sub(r'<pre[^>]*>.*?</pre>', replace_pre_code, html, flags=re.DOTALL | re.IGNORECASE)
    
    # 2. 处理内联 <code>...</code>（保留为 `...`）
    def replace_inline_code(match):
        code_content = match.group(1)
        code_content = re.sub(r'<[^>]+>', '', code_content)
        code_content = unescape(code_content).strip()
        if code_content and '\n' not in code_content:  # 确保是内联的
            return f'`{code_content}`'
        return code_content
    
    html = re.sub(r'<code[^>]*>(.*?)</code>', replace_inline_code, html, flags=re.DOTALL | re.IGNORECASE)
    
    return html

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
        # include_images: 公式作为 img alt 存在，必须开启
        # include_formatting: 保留代码块等格式结构
        # favor_recall: 更贪心地保留内容（而非 favor_precision）
        result = trafilatura.extract(
            html,
            url=url,
            include_tables=True,
            include_images=True,        # 关键：公式作为 <img alt="TeX"> 存在
            include_formatting=True,    # 关键：保留代码块等格式结构
            include_links=False,
            output_format="markdown",
            favor_recall=True,          # 关键：更贪心保留内容
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
        
        # 后处理：将 Wikipedia 数学公式图片转换为 LaTeX 格式
        # Wikipedia 公式渲染为 <img alt="LaTeX"> 形式
        text = _restore_wiki_math_images(text)
        text = _restore_inline_code(text)

        return text, images

    except ImportError:
        _LOGGER.warning("trafilatura not installed, skipping")
        return "", []
    except Exception as exc:
        _LOGGER.warning("trafilatura_extract_failed url=%s error=%s", url, exc)
        return "", []


def _restore_wiki_math_images(markdown: str) -> str:
    """将 Wikipedia 数学公式图片还原为 LaTeX 格式。
    
    Wikipedia 公式渲染后会变成 ![{\\displaystyle ...}](url) 形式，
    URL 中通常包含 /math/，alt 文本就是原始 LaTeX。
    """
    import re
    
    # 匹配 markdown 图片：![alt](url "title")
    img_pattern = re.compile(r'!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
    
    def replace_math_img(match):
        alt = match.group(1).strip()
        url = match.group(2)
        
        # Wikipedia 的公式图片 URL 常含 /math/，alt 常含 TeX
        # 也可能是 {\displaystyle ...} 或其他 LaTeX 语法
        is_math_url = "/math/" in url or "wikimedia.org/api/rest_v1/media/math" in url
        is_math_alt = alt and (
            alt.startswith("{\\displaystyle") or 
            alt.startswith("\\") or
            "{" in alt and "\\" in alt
        )
        
        if is_math_url or is_math_alt:
            if alt:
                # 判断是行内公式还是块级公式
                if len(alt) > 50 or "\\sum" in alt or "\\frac" in alt or "\\int" in alt:
                    return f"\n\n$${alt}$$\n\n"  # 块级公式
                else:
                    return f"${alt}$"  # 行内公式
        
        return match.group(0)  # 保持原样
    
    return img_pattern.sub(replace_math_img, markdown)


def _restore_inline_code(markdown: str) -> str:
    """确保内联代码格式正确。
    
    有时候 <code> 被转换为普通文本，需要恢复反引号。
    """
    # 这个函数主要作为占位符，实际代码块应该已经被 include_formatting 保留
    return markdown


def _extract_with_beautifulsoup(soup: BeautifulSoup, url: str) -> str:
    """使用 BeautifulSoup 提取正文（回退方案）。"""
    from urllib.parse import urlparse

    # 移除无用标签
    for tag in soup(["script", "style", "noscript", "nav", "footer", "aside"]):
        tag.decompose()

    # 针对 Wikipedia 的特化清理
    domain = urlparse(url).netloc.lower()
    if "wikipedia.org" in domain:
        # 先提取并替换数学公式，将 <math> 标签替换为 LaTeX 文本
        for math_tag in soup.find_all("math"):
            annotation = math_tag.find("annotation", attrs={"encoding": "application/x-tex"})
            if annotation and annotation.string:
                # 将 LaTeX 公式转换为 Markdown 格式 $$...$$
                latex_text = annotation.string.strip()
                # 替换 math 标签为可读的 LaTeX
                math_tag.replace_with(f" $${latex_text}$$ ")
            else:
                # 如果没有 annotation，尝试直接获取 alttext
                alttext = math_tag.get("alttext", "")
                if alttext:
                    math_tag.replace_with(f" $${alttext}$$ ")
        
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



def extract_images_from_pdf_bytes(pdf_bytes: bytes) -> List[Dict[str, Any]]:
    """从 PDF 字节流中以高保真度提取图片。
    
    Returns:
        List of dicts: [{"src": "data:image/png;base64,...", "alt": "...", "page": 1, "ext": "png"}]
    """
    images = []
    try:
        import pymupdf  # fitz
        import base64
        
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page_num, page in enumerate(doc):
                # get_images returns (xref, smask, width, height, bpc, colorspace, alt. colorspace, name, filter, referencer)
                for img_index, img in enumerate(page.get_images(full=True)):
                    try:
                        xref = img[0]
                        base_image = doc.extract_image(xref)
                        if base_image:
                            image_ext = base_image.get("ext", "png")
                            image_data = base_image.get("image")
                            if image_data:
                                # 转换为 base64 data URI (用于前端展示或 Ingest 处理)
                                b64_data = base64.b64encode(image_data).decode('utf-8')
                                images.append({
                                    "src": f"data:image/{image_ext};base64,{b64_data}",
                                    "data": image_data, # Raw bytes
                                    "ext": image_ext,
                                    "alt": f"PDF Page {page_num+1} Image {img_index+1}",
                                    "page": page_num + 1,
                                    "element_id": f"img_p{page_num+1}_{img_index+1}"
                                })
                    except Exception as e:
                        _LOGGER.warning(f"Failed to extract image {img_index} from page {page_num}: {e}")
        
        _LOGGER.info(f"Extracted {len(images)} images from PDF bytes")
        return images
    except ImportError:
        _LOGGER.warning("pymupdf not installed, cannot extract images")
        return []
    except Exception as e:
        _LOGGER.warning(f"extract_images_from_pdf_bytes failed: {e}")
        return []

# 日志记录器
import logging
_LOGGER = logging.getLogger("article_agent.tools_files")


def _download_from_minio(minio_path: str) -> str:
    """从 MinIO 下载文件到本地临时目录。
    
    Args:
        minio_path: MinIO 对象路径 (如 article/uploads/xxx.pdf)
        
    Returns:
        本地临时文件路径
    """
    import os
    import tempfile
    import uuid
    
    try:
        from minio import Minio
    except ImportError:
        _LOGGER.error("minio package not installed, cannot download from MinIO")
        raise ImportError("minio package required for MinIO downloads")
    
    # 从环境变量读取 MinIO 配置
    minio_endpoint = os.environ.get("MINIO_ENDPOINT", "minio:9000")
    minio_access_key = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    minio_secret_key = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
    minio_bucket = os.environ.get("MINIO_BUCKET", "cv-bucket")
    minio_secure = os.environ.get("MINIO_SECURE", "false").lower() == "true"
    
    _LOGGER.info(f"Downloading from MinIO: {minio_path} (endpoint={minio_endpoint}, bucket={minio_bucket})")
    
    client = Minio(
        minio_endpoint,
        access_key=minio_access_key,
        secret_key=minio_secret_key,
        secure=minio_secure
    )
    
    # 创建临时文件
    temp_dir = "/data/workspace/tmp"
    os.makedirs(temp_dir, exist_ok=True)
    
    filename = os.path.basename(minio_path)
    local_path = os.path.join(temp_dir, f"{uuid.uuid4().hex[:8]}_{filename}")
    
    # 下载文件
    client.fget_object(minio_bucket, minio_path, local_path)
    _LOGGER.info(f"Downloaded MinIO file to: {local_path}")
    
    return local_path


def load_text_from_file_sync(path: str, max_text_chars: int = 60000) -> Dict[str, Any]:
    """从本地文件加载文本内容 (同步版本)。

    当前支持：
      - .txt / .md：按 UTF-8 文本读取；
      - .pdf：使用 pymupdf4llm 转换为 Markdown（支持表格、公式、图片）；
      - MinIO 路径 (article/uploads/...)：先下载到本地再处理；
    其它复杂格式暂不处理，返回空文本占位。
    """
    
    # 检查是否是 MinIO 路径
    if path.startswith("article/") or path.startswith("minio://"):
        try:
            clean_path = path.replace("minio://", "")
            local_path = _download_from_minio(clean_path)
            path = local_path
        except Exception as e:
            _LOGGER.error(f"Failed to download from MinIO: {e}")
            return {"path": path, "text": f"[MinIO下载失败: {e}]", "images": []}

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在：{path}")

    suffix = p.suffix.lower()
    text = ""
    images = []

    if suffix == ".pdf":
        try:
            import pymupdf4llm
            import pymupdf
            
            # 提取文本 (Markdown格式)
            md_text = pymupdf4llm.to_markdown(str(p))
            text = md_text
            _LOGGER.info(f"PDF converted to Markdown using pymupdf4llm: {len(text)} chars")
            
            # 提取图片
            try:
                doc = pymupdf.open(str(p))
                for page_num, page in enumerate(doc):
                    for img_index, img in enumerate(page.get_images(full=True)):
                        try:
                            xref = img[0]
                            base_image = doc.extract_image(xref)
                            if base_image:
                                image_ext = base_image.get("ext", "png")
                                image_data = base_image.get("image")
                                if image_data:
                                    # 转换为 base64 data URI
                                    import base64
                                    b64_data = base64.b64encode(image_data).decode('utf-8')
                                    images.append({
                                        "src": f"data:image/{image_ext};base64,{b64_data}",
                                        "alt": f"PDF Page {page_num+1} Image {img_index+1}",
                                        "page": page_num + 1,
                                    })
                        except Exception as e:
                            _LOGGER.warning(f"Failed to extract image from PDF: {e}")
                doc.close()
                _LOGGER.info(f"Extracted {len(images)} images from PDF")
            except Exception as e:
                _LOGGER.warning(f"Failed to extract PDF images: {e}")
                
        except ImportError:
            _LOGGER.warning("pymupdf4llm not installed, falling back to PyPDF2")
            # 回退到 PyPDF2
            reader = PdfReader(str(p))
            parts: List[str] = []
            for page in reader.pages:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:
                    continue
            text = "\n".join(parts)
            
    elif suffix in (".txt", ".md", ".markdown"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                text = f.read()
            if len(text) > max_text_chars:
                text = text[:max_text_chars] + "\n...(truncated)"
        except Exception as e:
            _LOGGER.warning(f"Failed to read text file {path}: {e}")
            
    else:
        # 其他格式暂不支持
        pass

    return {
        "path": str(path),
        "text": text,
        "images": images,
        "title": p.name
    }


async def load_text_from_file(path: str, max_text_chars: int = 60000) -> Dict[str, Any]:
    """从本地文件加载文本内容 (异步版本)。
    
    内部使用 asyncio.to_thread 调用同步版本，避免阻塞事件循环。
    """
    import asyncio
    return await asyncio.to_thread(load_text_from_file_sync, path, max_text_chars)
    

async def load_uploaded_file_text(path: str, max_text_chars: int = 60000) -> str:
    """符合提示词约定的文件文本读取工具封装 (Async Wrapper)。

    返回文件文本字符串，用于 Deep Agent 的 load_uploaded_file_text 工具。
    """
    data = await load_text_from_file(path, max_text_chars)
    return data.get("text", "")


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
