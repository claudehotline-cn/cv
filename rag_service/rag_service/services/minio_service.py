"""MinIO 文件存储服务"""

import logging
import tempfile
import os
from typing import Optional
from minio import Minio
from minio.error import S3Error
from ..config import settings

logger = logging.getLogger(__name__)


class MinIOService:
    """MinIO 文件存储服务"""
    
    def __init__(self):
        self.client: Optional[Minio] = None
        self.bucket = settings.minio_bucket
        self._init_client()
    
    def _init_client(self):
        """初始化 MinIO 客户端"""
        try:
            self.client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure
            )
            
            # 确保 bucket 存在
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info(f"Created MinIO bucket: {self.bucket}")
            
            logger.info(f"MinIO client initialized, bucket: {self.bucket}")
            
        except Exception as e:
            logger.error(f"Failed to initialize MinIO client: {e}")
            self.client = None
    
    def upload_file(self, file_content: bytes, object_name: str, content_type: str = "application/octet-stream") -> Optional[str]:
        """
        上传文件到 MinIO
        
        Args:
            file_content: 文件内容
            object_name: 对象名称（存储路径）
            content_type: 文件类型
            
        Returns:
            成功返回对象名称，失败返回 None
        """
        if not self.client:
            self._init_client()
            if not self.client:
                logger.error("MinIO client not available")
                return None
        
        try:
            # 使用临时文件上传
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(file_content)
                tmp_path = tmp.name
            
            try:
                self.client.fput_object(
                    self.bucket,
                    object_name,
                    tmp_path,
                    content_type=content_type
                )
                logger.info(f"Uploaded to MinIO: {object_name}")
                return object_name
            finally:
                os.remove(tmp_path)
                
        except S3Error as e:
            logger.error(f"MinIO upload error: {e}")
            return None
        except Exception as e:
            logger.error(f"Upload error: {e}")
            return None

    def upload_from_path(self, file_path: str, object_name: str, content_type: str = "application/octet-stream") -> Optional[str]:
        """
        从本地文件路径上传到 MinIO
        
        Args:
            file_path: 本地文件路径
            object_name: 对象名称
            content_type: 文件类型
        """
        if not self.client:
            self._init_client()
            if not self.client:
                return None
        
        try:
            self.client.fput_object(
                self.bucket,
                object_name,
                file_path,
                content_type=content_type
            )
            logger.info(f"Uploaded to MinIO from path: {object_name}")
            return object_name
        except Exception as e:
            logger.error(f"Upload from path error: {e}")
            return None
    
    def download_file(self, object_name: str) -> Optional[str]:
        """
        从 MinIO 下载文件到临时目录
        
        Args:
            object_name: 对象名称
            
        Returns:
            成功返回临时文件路径，失败返回 None
        """
        if not self.client:
            self._init_client()
            if not self.client:
                logger.error("MinIO client not available")
                return None
        
        try:
            # 获取文件扩展名
            _, ext = os.path.splitext(object_name)
            
            # 下载到临时文件
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp_path = tmp.name
            
            self.client.fget_object(self.bucket, object_name, tmp_path)
            logger.info(f"Downloaded from MinIO: {object_name} -> {tmp_path}")
            return tmp_path
            
        except S3Error as e:
            logger.error(f"MinIO download error: {e}")
            return None
        except Exception as e:
            logger.error(f"Download error: {e}")
            return None
    
    def delete_file(self, object_name: str) -> bool:
        """删除 MinIO 中的文件"""
        if not self.client:
            return False
        
        try:
            self.client.remove_object(self.bucket, object_name)
            logger.info(f"Deleted from MinIO: {object_name}")
            return True
        except Exception as e:
            logger.error(f"Delete error: {e}")
            return False
    
    def get_presigned_url(self, object_name: str, expires_hours: int = 24) -> Optional[str]:
        """
        生成预签名 URL (用于临时访问)
        
        Args:
            object_name: 对象名称
            expires_hours: 过期时间（小时）
            
        Returns:
            预签名 URL
        """
        if not self.client:
            self._init_client()
            if not self.client:
                return None
        
        try:
            from datetime import timedelta
            url = self.client.presigned_get_object(
                self.bucket,
                object_name,
                expires=timedelta(hours=expires_hours)
            )
            return url
        except Exception as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            return None
    
    def get_public_url(self, object_name: str) -> str:
        """
        生成公开访问 URL (需要 bucket 配置为 public)
        
        Args:
            object_name: 对象名称
            
        Returns:
            公开 URL
        """
        protocol = "https" if settings.minio_secure else "http"
        return f"{protocol}://{settings.minio_endpoint}/{self.bucket}/{object_name}"


# 单例
minio_service = MinIOService()
