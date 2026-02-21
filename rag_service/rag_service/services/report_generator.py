"""
可视化报告生成器

功能：
- 基于检索结果自动生成报告
- 支持 Markdown/HTML 输出格式
- 集成 VLM 分析图表/图片
- 可选图表生成 (Mermaid)
"""

import logging
from typing import List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from ..config import settings
from .multimodal_retriever import multimodal_retriever
from .vlm_service import vlm_service

logger = logging.getLogger(__name__)


@dataclass
class Report:
    """报告对象"""
    title: str
    content: str
    format: str  # markdown | html
    sections: List[dict] = field(default_factory=list)
    images: List[dict] = field(default_factory=list)
    charts: List[str] = field(default_factory=list)  # Mermaid 图表代码
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    word_count: int = 0


class ReportGenerator:
    """可视化报告生成器"""
    
    def __init__(self):
        logger.info("Initialized report generator")
    
    async def generate(
        self,
        topic: str,
        knowledge_base_id: int,
        format: str = "markdown",
        include_charts: bool = True,
        max_sections: int = 5,
        section_queries: Optional[List[str]] = None,
    ) -> Report:
        """
        生成报告
        
        Args:
            topic: 报告主题
            knowledge_base_id: 知识库 ID
            format: 输出格式 (markdown/html)
            include_charts: 是否生成图表
            max_sections: 最大章节数
            section_queries: 自定义章节查询 (可选)
            
        Returns:
            Report 报告对象
        """
        # 1. 生成章节查询
        if section_queries is None:
            section_queries = await self._generate_section_queries(topic, max_sections)
        
        # 2. 逐章节检索和生成
        sections = []
        all_images = []
        
        for i, query in enumerate(section_queries, 1):
            section = await self._generate_section(
                section_num=i,
                query=query,
                knowledge_base_id=knowledge_base_id
            )
            sections.append(section)
            all_images.extend(section.get("images", []))
        
        # 3. 生成图表 (可选)
        charts = []
        if include_charts:
            charts = await self._generate_charts(topic, sections)
        
        # 4. 组装报告
        content = self._format_report(
            title=topic,
            sections=sections,
            charts=charts,
            format=format
        )
        
        report = Report(
            title=topic,
            content=content,
            format=format,
            sections=sections,
            images=all_images,
            charts=charts,
            word_count=len(content)
        )
        
        return report
    
    async def _generate_section_queries(
        self,
        topic: str,
        max_sections: int
    ) -> List[str]:
        """
        根据主题生成章节查询
        
        使用 VLM/LLM 拆分主题为多个子查询
        """
        prompt = f"""请将以下报告主题拆分为 {max_sections} 个章节子主题，用于信息检索。

报告主题：{topic}

要求：
1. 每个子主题应该是一个具体的检索查询
2. 子主题应该覆盖报告的各个方面
3. 按逻辑顺序排列
4. 直接输出查询列表，每行一个

输出格式（仅输出查询，不要编号）：
"""
        
        response = await vlm_service.analyze_image(
            # 使用空图像占位，实际只需要文本生成
            # 这里简化处理，未来可以使用专门的 LLM 服务
            image=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82',
            prompt=prompt
        )
        
        # 解析响应
        queries = []
        for line in response.content.strip().split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                # 移除可能的编号前缀
                line = line.lstrip('0123456789.-) ')
                if line:
                    queries.append(line)
        
        return queries[:max_sections]
    
    async def _generate_section(
        self,
        section_num: int,
        query: str,
        knowledge_base_id: int
    ) -> dict:
        """
        生成单个章节
        """
        # 检索相关内容
        search_result = await multimodal_retriever.retrieve(
            query=query,
            knowledge_base_id=knowledge_base_id,
            top_k=5
        )
        
        # 构建上下文
        context_parts = []
        sources = []
        for r in search_result.text_results:
            context_parts.append(r.content)
            sources.append({
                "document_id": r.document_id,
                "content_preview": r.content[:100]
            })
        
        context = "\n\n".join(context_parts)
        
        # 使用 VLM 生成章节内容
        prompt = f"""基于以下检索到的信息，为报告撰写一个章节。

章节主题：{query}

参考信息：
{context}

要求：
1. 内容要准确、专业
2. 用 Markdown 格式输出
3. 包含必要的小标题
4. 长度约 200-400 字
"""
        
        # 简化处理：直接使用检索内容作为章节基础
        response = await vlm_service.analyze_image(
            image=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82',
            prompt=prompt
        )
        
        return {
            "number": section_num,
            "title": query,
            "content": response.content,
            "sources": sources,
            "images": search_result.image_results
        }
    
    async def _generate_charts(
        self,
        topic: str,
        sections: List[dict]
    ) -> List[str]:
        """
        生成 Mermaid 图表
        """
        # 生成一个简单的结构图
        section_titles = [s["title"] for s in sections]
        
        # 构建 Mermaid 思维导图
        mermaid_code = f"mindmap\n  root(({topic}))\n"
        for title in section_titles:
            # 清理标题中的特殊字符
            clean_title = title.replace("(", "").replace(")", "").replace("[", "").replace("]", "")
            mermaid_code += f"    {clean_title}\n"
        
        return [mermaid_code]
    
    def _format_report(
        self,
        title: str,
        sections: List[dict],
        charts: List[str],
        format: str
    ) -> str:
        """
        格式化报告输出
        """
        if format == "markdown":
            return self._format_markdown(title, sections, charts)
        elif format == "html":
            return self._format_html(title, sections, charts)
        else:
            return self._format_markdown(title, sections, charts)
    
    def _format_markdown(
        self,
        title: str,
        sections: List[dict],
        charts: List[str]
    ) -> str:
        """
        生成 Markdown 格式报告
        """
        lines = [
            f"# {title}",
            "",
            f"*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
            "",
            "---",
            "",
        ]
        
        # 目录
        lines.append("## 目录\n")
        for s in sections:
            lines.append(f"- [{s['title']}](#{s['number']})")
        lines.append("")
        
        # 图表 (如果有)
        if charts:
            lines.append("## 概览\n")
            lines.append("```mermaid")
            lines.append(charts[0])
            lines.append("```")
            lines.append("")
        
        # 各章节内容
        for s in sections:
            lines.append(f"## {s['number']}. {s['title']}\n")
            lines.append(s["content"])
            lines.append("")
            
            # 来源引用
            if s.get("sources"):
                lines.append("**参考来源：**\n")
                for src in s["sources"][:3]:
                    lines.append(f"- 文档 {src['document_id']}")
                lines.append("")
        
        return "\n".join(lines)
    
    def _format_html(
        self,
        title: str,
        sections: List[dict],
        charts: List[str]
    ) -> str:
        """
        生成 HTML 格式报告
        """
        # 简化的 HTML 模板
        html_parts = [
            "<!DOCTYPE html>",
            "<html><head>",
            f"<title>{title}</title>",
            "<meta charset='utf-8'>",
            "<style>",
            "body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }",
            "h1 { color: #333; } h2 { color: #666; border-bottom: 1px solid #eee; }",
            ".section { margin: 20px 0; }",
            ".sources { font-size: 0.9em; color: #888; }",
            "</style>",
            "</head><body>",
            f"<h1>{title}</h1>",
            f"<p><em>生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</em></p>",
            "<hr>",
        ]
        
        for s in sections:
            html_parts.append(f"<div class='section'>")
            html_parts.append(f"<h2>{s['number']}. {s['title']}</h2>")
            # 简单转换 Markdown 到 HTML (仅处理段落)
            content_html = s["content"].replace("\n\n", "</p><p>")
            html_parts.append(f"<p>{content_html}</p>")
            html_parts.append("</div>")
        
        html_parts.append("</body></html>")
        
        return "\n".join(html_parts)


# 单例
report_generator = ReportGenerator()
