"""网页内容抓取器"""

import logging
import httpx
import trafilatura
from typing import Optional
from dataclasses import dataclass
from urllib.parse import urlparse

from ..config import settings

logger = logging.getLogger(__name__)


@dataclass
class CrawledPage:
    """抓取的网页内容"""
    url: str
    title: str
    content: str
    metadata: dict


class WebCrawler:
    """网页内容抓取器"""
    
    def __init__(self, timeout: int = None):
        self.timeout = timeout or settings.web_crawl_timeout
    
    async def crawl(self, url: str) -> CrawledPage:
        """抓取网页内容"""
        logger.info(f"Crawling URL: {url}")
        
        try:
            # 下载网页
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                response.raise_for_status()
                html = response.text
            
            # 使用trafilatura提取正文
            extracted = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=True,
                include_links=False,
                output_format='txt',
                favor_precision=True,
            )
            
            if not extracted:
                raise ValueError(f"Failed to extract content from {url}")
            
            # 提取标题
            title = trafilatura.extract(html, output_format='xml')
            title = self._extract_title(html, url)
            
            # 解析域名作为来源
            parsed = urlparse(url)
            domain = parsed.netloc
            
            return CrawledPage(
                url=url,
                title=title,
                content=extracted,
                metadata={
                    "source": url,
                    "domain": domain,
                    "type": "webpage",
                }
            )
            
        except httpx.HTTPError as e:
            logger.error(f"HTTP error crawling {url}: {e}")
            raise ValueError(f"Failed to fetch URL: {e}")
        except Exception as e:
            logger.error(f"Error crawling {url}: {e}")
            raise
    
    def _extract_title(self, html: str, fallback_url: str) -> str:
        """从HTML中提取标题"""
        import re
        
        # 尝试匹配title标签
        match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # 尝试匹配h1标签
        match = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # 使用URL作为回退
        parsed = urlparse(fallback_url)
        return parsed.path.split('/')[-1] or parsed.netloc


# 单例
web_crawler = WebCrawler()
