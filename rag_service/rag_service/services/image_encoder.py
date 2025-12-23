"""
图像编码服务 - 图像预处理和向量化

功能：
- 图像预处理 (resize, 压缩)
- Base64 编码转换
- 图像向量化 (通过 VLM 提取特征描述 -> 文本向量化)
"""

import logging
import base64
import io
from typing import List, Optional, Union, Tuple
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ..config import settings
from .vlm_service import vlm_service
from .embedder import embedding_service

logger = logging.getLogger(__name__)


@dataclass
class ImageInfo:
    """图像信息"""
    width: int
    height: int
    format: str
    size_bytes: int
    data: bytes


class ImageEncoder:
    """图像编码服务"""
    
    def __init__(self):
        self.max_size = settings.max_image_size
        self.supported_types = set(settings.supported_image_types.split(','))
        self.target_size = (1024, 1024)  # 预处理目标尺寸
        self.quality = 85  # JPEG 压缩质量
        
        logger.info(f"Initialized image encoder with supported types: {self.supported_types}")
    
    def is_supported(self, filename: str) -> bool:
        """检查文件类型是否支持"""
        ext = Path(filename).suffix.lower()
        return ext in self.supported_types
    
    def get_image_info(self, image_data: bytes) -> ImageInfo:
        """获取图像信息"""
        img = Image.open(io.BytesIO(image_data))
        return ImageInfo(
            width=img.width,
            height=img.height,
            format=img.format or "UNKNOWN",
            size_bytes=len(image_data),
            data=image_data
        )
    
    def preprocess(
        self,
        image_data: bytes,
        max_dimension: int = 1024,
        quality: int = 85
    ) -> bytes:
        """
        预处理图像：缩放和压缩
        
        Args:
            image_data: 原始图像数据
            max_dimension: 最大边长
            quality: JPEG 压缩质量
            
        Returns:
            处理后的图像数据
        """
        img = Image.open(io.BytesIO(image_data))
        
        # 转换为 RGB (处理 RGBA 或其他模式)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        # 计算缩放比例
        width, height = img.size
        if max(width, height) > max_dimension:
            ratio = max_dimension / max(width, height)
            new_size = (int(width * ratio), int(height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            logger.debug(f"Resized image from {width}x{height} to {new_size[0]}x{new_size[1]}")
        
        # 压缩为 JPEG
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=quality, optimize=True)
        result = buffer.getvalue()
        
        logger.debug(f"Compressed image from {len(image_data)} to {len(result)} bytes")
        return result
    
    def to_base64(self, image_data: bytes, mime_type: str = "image/jpeg") -> str:
        """
        将图像转换为 base64 编码的 data URL
        
        Args:
            image_data: 图像数据
            mime_type: MIME 类型
            
        Returns:
            data URL 格式的 base64 字符串
        """
        b64 = base64.b64encode(image_data).decode('utf-8')
        return f"data:{mime_type};base64,{b64}"
    
    def from_base64(self, data_url: str) -> bytes:
        """
        从 base64 data URL 解码图像
        
        Args:
            data_url: data URL 格式的字符串
            
        Returns:
            图像数据
        """
        # 移除 data URL 前缀
        if ',' in data_url:
            data_url = data_url.split(',', 1)[1]
        return base64.b64decode(data_url)
    
    async def encode(self, image: Union[bytes, str, Path]) -> Tuple[List[float], str]:
        """
        将图像编码为向量
        
        策略：使用 VLM 生成图像描述，然后对描述进行文本向量化
        
        Args:
            image: 图像数据 (bytes/文件路径/base64)
            
        Returns:
            (向量, 图像描述) 元组
        """
        # 获取图像数据
        if isinstance(image, bytes):
            image_data = image
        elif isinstance(image, (str, Path)):
            path = Path(image)
            if path.exists():
                image_data = path.read_bytes()
            else:
                # 假设是 base64
                image_data = self.from_base64(str(image))
        else:
            raise ValueError(f"Unsupported image type: {type(image)}")
        
        # 预处理
        processed = self.preprocess(image_data)
        
        # 使用 VLM 生成描述
        description = await vlm_service.describe_image(processed)
        
        # 对描述进行文本向量化
        embedding = embedding_service.embed_text(description)
        
        logger.debug(f"Encoded image to {len(embedding)}-dim vector with description length {len(description)}")
        return embedding, description
    
    async def encode_batch(
        self,
        images: List[Union[bytes, str, Path]]
    ) -> List[Tuple[List[float], str]]:
        """
        批量编码图像
        
        Args:
            images: 图像列表
            
        Returns:
            (向量, 描述) 元组列表
        """
        results = []
        for img in images:
            try:
                result = await self.encode(img)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to encode image: {e}")
                # 返回空向量和错误描述
                results.append(([], f"Error: {str(e)}"))
        return results
    
    def extract_from_pdf(self, pdf_path: str) -> List[Tuple[bytes, int]]:
        """
        从 PDF 提取图片
        
        Args:
            pdf_path: PDF 文件路径
            
        Returns:
            (图片数据, 页码) 列表
        """
        import fitz  # PyMuPDF
        
        images = []
        try:
            doc = fitz.open(pdf_path)
            for page_index in range(len(doc)):
                page = doc[page_index]
                image_list = page.get_images(full=True)
                
                for img_index, img in enumerate(image_list):
                    xref = img[0]
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    
                    # 过滤过小的图片 (如图标)
                    if len(image_bytes) < 1024:  # 1KB
                        continue
                        
                    images.append((image_bytes, page_index + 1))
                    
            doc.close()
            logger.info(f"Extracted {len(images)} images from PDF {pdf_path}")
        except Exception as e:
            logger.error(f"Failed to extract images from PDF {pdf_path}: {e}")
        
        return images

    def extract_from_docx(self, file_path: str) -> List[Tuple[bytes, int]]:
        """
        从 Word (.docx) 文件中提取图片
        
        Args:
            file_path: Word文件路径
            
        Returns:
            List[Tuple[bytes, int]]: [(图片数据, 0), ...] Word无分页概念，页码统一为0
        """
        import zipfile
        
        images = []
        try:
            with zipfile.ZipFile(file_path) as z:
                # 获取所有文件列表
                all_files = z.namelist()
                # 过滤出媒体文件 (word/media/)
                media_files = [f for f in all_files if f.startswith('word/media/') and f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
                
                # 排序以保持顺序
                media_files.sort()
                
                for media_file in media_files:
                    try:
                        img_data = z.read(media_file)
                        # 简单的最小尺寸过滤 (忽略图标等)
                        if len(img_data) > 1024:  # > 1KB
                            images.append((img_data, 0))
                    except Exception as e:
                        logger.warning(f"Failed to read media file {media_file} from {file_path}: {e}")
                        
            logger.info(f"Extracted {len(images)} images from Word: {file_path}")
            return images
            
        except zipfile.BadZipFile:
            logger.error(f"Invalid DOCX file (not a zip): {file_path}")
            return []
        except Exception as e:
            logger.error(f"Error extracting images from DOCX {file_path}: {e}")
            return []


# 单例
image_encoder = ImageEncoder()
