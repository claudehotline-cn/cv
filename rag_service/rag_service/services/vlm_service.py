"""Vision-Language model service via vLLM (OpenAI-compatible API)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Union, cast

from ..config import settings
from .vllm_client import chat_completion, chat_completion_stream, image_to_data_url


logger = logging.getLogger(__name__)


@dataclass
class VLMResponse:
    content: str
    model: str
    usage: Optional[dict] = None


class VLMService:
    def __init__(self):
        self.model = settings.vlm_model
        self.base_url = settings.vllm_base_url
        self.api_key = settings.vllm_api_key
        self._video_support_checked = False
        self._video_support = True

        logger.info("Initialized VLM service (vLLM): %s @ %s", self.model, self.base_url)

    def _image_part(self, image: Union[bytes, str, Path], mime_type: str = "image/jpeg") -> Dict[str, Any]:
        return {
            "type": "image_url",
            "image_url": {"url": image_to_data_url(image, mime_type=mime_type)},
        }

    async def analyze_image(self, image: Union[bytes, str, Path], prompt: str = "请描述这张图片的内容。") -> VLMResponse:
        return await self.analyze_images([image], prompt)

    async def analyze_images(self, images: List[Union[bytes, str, Path]], prompt: str = "请描述这些图片的内容。") -> VLMResponse:
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for img in images:
            content.append(self._image_part(img))

        messages = [{"role": "user", "content": content}]
        text = await chat_completion(
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model,
            messages=messages,
            temperature=0.2,
            timeout_sec=180,
        )
        return VLMResponse(content=text, model=self.model)

    async def analyze_images_stream(
        self,
        images: List[Union[bytes, str, Path]],
        prompt: str = "请描述这些图片的内容。",
        history: Optional[List[dict]] = None,
    ) -> AsyncGenerator[str, None]:
        messages: List[Dict[str, Any]] = []
        if history:
            for msg in history:
                role = msg.get("role") or "user"
                content = msg.get("content") or ""
                messages.append({"role": role, "content": str(content)})

        content_parts: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for img in images:
            content_parts.append(self._image_part(img))
        messages.append({"role": "user", "content": content_parts})

        async for chunk in chat_completion_stream(
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model,
            messages=messages,
            temperature=0.2,
            timeout_sec=180,
        ):
            yield chunk

    async def analyze_image_stream(
        self,
        image: Union[bytes, str, Path],
        prompt: str = "请描述这张图片的内容。",
    ) -> AsyncGenerator[str, None]:
        async for c in self.analyze_images_stream([image], prompt):
            yield c

    async def ocr(self, image: Union[bytes, str, Path]) -> str:
        prompt = """请识别这张图片中的所有文字内容。
要求：
1. 保持原有的文字顺序和格式
2. 如果有表格，尽量保持表格结构
3. 只输出识别到的文字，不要添加解释"""
        r = await self.analyze_image(image, prompt)
        return r.content

    async def describe_image(self, image: Union[bytes, str, Path]) -> str:
        prompt = """请详细描述这张图片的内容，包括：
1. 图片的主要元素和场景
2. 图片中的文字（如果有）
3. 图片的整体风格和用途推测"""
        r = await self.analyze_image(image, prompt)
        return r.content

    async def check_video_support(self) -> bool:
        # vLLM-omni model is multimodal; we implement video via frames.
        self._video_support_checked = True
        self._video_support = True
        return True

    async def analyze_video_frames(
        self,
        frames: List[bytes],
        timestamps: List[float],
        audio_transcript: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> VLMResponse:
        frame_desc = ", ".join([f"帧{i+1}({t:.1f}秒)" for i, t in enumerate(timestamps)])
        default_prompt = f"""这是一段视频的关键帧截图，时间轴为：{frame_desc}。

请分析这段视频的内容，包括：
1. 视频的主要内容和场景
2. 视频中发生的事件或动作
3. 关键信息和要点总结"""
        if audio_transcript:
            default_prompt += f"""

视频的音频转写内容如下：
---
{audio_transcript}
---

请结合画面和音频内容进行综合分析。"""

        final_prompt = prompt or default_prompt
        images = cast(List[Union[bytes, str, Path]], list(frames))
        return await self.analyze_images(images, final_prompt)

    async def analyze_chart(self, image: Union[bytes, str, Path]) -> VLMResponse:
        prompt = """你是一个专业的数据分析师。请仔细分析这张图表，并完成以下任务：

1. **提取数据**：尽可能多地提取图表中的原始数据，并将其整理为标准的 JSON 格式输出。
2. **趋势分析**：用简练的语言描述数据之间的关系、趋势、峰值和异常值。
3. **结论总结**：基于数据推导出核心结论。

请严格按照以下格式输出：
```json
{
  "data": {},
  "analysis": "...",
  "conclusion": "..."
}
```
"""
        return await self.analyze_image(image, prompt)


vlm_service = VLMService()
