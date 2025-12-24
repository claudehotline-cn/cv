"""
视觉语言模型服务 - 封装 Qwen3-VL 调用

支持：
- 图像理解 (单图/多图)
- 视频理解 (原生支持或降级模式)
- OCR 文字识别
- 图像描述生成
"""

import logging
import base64
import json
import httpx
from typing import AsyncGenerator, List, Optional, Union
from dataclasses import dataclass
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)


@dataclass
class VLMResponse:
    """VLM 响应结果"""
    content: str
    model: str
    usage: Optional[dict] = None


class VLMService:
    """视觉语言模型服务 (Qwen3-VL via Ollama)"""
    
    def __init__(self):
        self.model = settings.vlm_model
        self.base_url = settings.ollama_base_url
        self._video_support_checked = False
        self._video_support = False
        
        logger.info(f"Initialized VLM service: {self.model} @ {self.base_url}")
    
    def _image_to_base64(self, image: Union[bytes, str, Path]) -> str:
        """将图像转换为 base64 编码"""
        if isinstance(image, bytes):
            return base64.b64encode(image).decode('utf-8')
        elif isinstance(image, (str, Path)):
            path = Path(image)
            if path.exists():
                return base64.b64encode(path.read_bytes()).decode('utf-8')
            # 可能已经是 base64 字符串
            return str(image)
        raise ValueError(f"Unsupported image type: {type(image)}")
    
    async def analyze_image(
        self,
        image: Union[bytes, str, Path],
        prompt: str = "请描述这张图片的内容。",
    ) -> VLMResponse:
        """
        分析单张图片
        
        Args:
            image: 图片数据 (bytes/文件路径/base64字符串)
            prompt: 分析提示词
            
        Returns:
            VLMResponse 包含分析结果
        """
        return await self.analyze_images([image], prompt)
    
    async def analyze_images(
        self,
        images: List[Union[bytes, str, Path]],
        prompt: str = "请描述这些图片的内容。",
    ) -> VLMResponse:
        """
        分析多张图片
        
        Args:
            images: 图片列表
            prompt: 分析提示词
            
        Returns:
            VLMResponse 包含分析结果
        """
        # 将图片转换为 base64 列表 (Ollama 原生格式)
        image_b64_list = [self._image_to_base64(img) for img in images]
        
        # Ollama chat API 调用 (原生视觉格式)
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "user",
                                "content": prompt,
                                "images": image_b64_list  # Ollama 原生格式
                            }
                        ],
                        "stream": False
                    }
                )
                response.raise_for_status()
                data = response.json()
                
                return VLMResponse(
                    content=data.get("message", {}).get("content", ""),
                    model=self.model,
                    usage=data.get("usage")
                )
            except httpx.HTTPError as e:
                logger.error(f"VLM API call failed: {e}")
                raise
    
    async def analyze_images_stream(
        self,
        images: List[Union[bytes, str, Path]],
        prompt: str = "请描述这些图片的内容。",
        history: List[dict] = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式分析多张图片
        
        Args:
            images: 图片列表
            prompt: 分析提示词
            history: 历史对话 [{"role": "user|assistant", "content": "..."}]
            
        Yields:
            逐块文本内容
        """
        image_b64_list = [self._image_to_base64(img) for img in images]
        
        # 构建消息列表（含历史）
        messages = []
        if history:
            for msg in history:
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                })
        
        # 添加当前用户消息（带图片）
        messages.append({
            "role": "user",
            "content": prompt,
            "images": image_b64_list
        })
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": True
                }
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            if content := data.get("message", {}).get("content"):
                                yield content
                        except json.JSONDecodeError:
                            continue
    
    async def analyze_image_stream(
        self,
        image: Union[bytes, str, Path],
        prompt: str = "请描述这张图片的内容。",
    ) -> AsyncGenerator[str, None]:
        """流式分析单张图片"""
        async for chunk in self.analyze_images_stream([image], prompt):
            yield chunk
    
    async def ocr(self, image: Union[bytes, str, Path]) -> str:
        """
        图像文字识别 (OCR)
        
        Args:
            image: 图片数据
            
        Returns:
            识别出的文字内容
        """
        prompt = """请识别这张图片中的所有文字内容。
要求：
1. 保持原有的文字顺序和格式
2. 如果有表格，尽量保持表格结构
3. 只输出识别到的文字，不要添加解释"""
        
        response = await self.analyze_image(image, prompt)
        return response.content
    
    async def describe_image(self, image: Union[bytes, str, Path]) -> str:
        """
        生成图像描述
        
        Args:
            image: 图片数据
            
        Returns:
            图像的详细描述
        """
        prompt = """请详细描述这张图片的内容，包括：
1. 图片的主要元素和场景
2. 图片中的文字（如果有）
3. 图片的整体风格和用途推测"""
        
        response = await self.analyze_image(image, prompt)
        return response.content
    
    async def check_video_support(self) -> bool:
        """
        检测当前 VLM 模型是否支持原生视频输入
        
        Returns:
            True 如果支持原生视频，False 否则
        """
        if self._video_support_checked:
            return self._video_support
        
        # 通过 Ollama API 获取模型信息
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/show",
                    json={"name": self.model}
                )
                response.raise_for_status()
                data = response.json()
                
                # 检查模型是否支持视频
                # Qwen2.5-VL 理论上支持视频，但需要验证 Ollama 实现
                model_info = data.get("modelfile", "").lower()
                template = data.get("template", "").lower()
                
                # 目前保守判断：默认不支持原生视频
                # 但如果是 Qwen3-VL，明确支持视频
                if "qwen3-vl" in self.model.lower():
                    self._video_support = True
                else:
                    self._video_support = "video" in model_info or "video" in template
                
                self._video_support_checked = True
                
                logger.info(f"VLM video support: {self._video_support}")
                return self._video_support
                
            except httpx.HTTPError as e:
                logger.warning(f"Failed to check video support: {e}")
                self._video_support = False
                self._video_support_checked = True
                return False
    
    async def analyze_video_frames(
        self,
        frames: List[bytes],
        timestamps: List[float],
        audio_transcript: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> VLMResponse:
        """
        分析视频帧序列 (降级模式)
        
        Args:
            frames: 视频帧列表 (图片数据)
            timestamps: 每帧对应的时间戳 (秒)
            audio_transcript: 音频转写文本 (可选)
            prompt: 自定义提示词 (可选)
            
        Returns:
            VLMResponse 包含视频分析结果
        """
        # 构建带时间戳的提示
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
        return await self.analyze_images(frames, final_prompt)


    async def analyze_chart(
        self,
        image: Union[bytes, str, Path]
    ) -> VLMResponse:
        """
        图表深度分析 (Chart QA)
        
        Args:
            image: 图片数据
            
        Returns:
            VLMResponse 包含 JSON 数据提取和分析
        """
        prompt = """你是一个专业的数据分析师。请仔细分析这张图表，并完成以下任务：

1. **提取数据**：尽可能多地提取图表中的原始数据，并将其整理为标准的 JSON 格式输出。
   - 如果是坐标图，提取坐标点。
   - 如果是柱状图或饼图，提取具体的数值和分类。

2. **趋势分析**：用简练的语言描述数据之间的关系、趋势、峰值和异常值。

3. **结论总结**：基于数据推导出核心结论。

请严格按照以下格式输出：
```json
{
    "data": { ...提取的数据结构... },
    "analysis": "趋势分析文本...",
    "conclusion": "结论总结文本..."
}
```
"""
        return await self.analyze_image(image, prompt)


# 单例
vlm_service = VLMService()
