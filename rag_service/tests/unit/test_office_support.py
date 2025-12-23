
import unittest
from unittest.mock import MagicMock, patch, mock_open
import sys
import os
from pathlib import Path

# 添加项目跟目录到 path
sys.path.insert(0, str(Path(__file__).parents[2]))

from rag_service.services.image_encoder import ImageEncoder

class TestOfficeSupport(unittest.TestCase):
    def setUp(self):
        self.encoder = ImageEncoder()

    @patch('zipfile.ZipFile')
    def test_extract_from_docx(self, mock_zipfile):
        # 模拟 ZipFile 上下文管理器
        mock_zip_instance = MagicMock()
        mock_zipfile.return_value.__enter__.return_value = mock_zip_instance
        
        # 模拟 namelist 返回文件列表
        mock_zip_instance.namelist.return_value = [
            'word/document.xml',
            'word/media/image1.png',
            'word/media/image2.jpg',
            'word/media/not_image.xml'
        ]
        
        # 模拟 read 方法返回图片数据
        def side_effect(filename):
            if filename.endswith('.png'):
                return b'fake_png_data_larger_than_1kb' * 100
            elif filename.endswith('.jpg'):
                return b'fake_jpg_data_larger_than_1kb' * 100
            return b'small'
            
        mock_zip_instance.read.side_effect = side_effect
        
        # 执行提取
        images = self.encoder.extract_from_docx("dummy.docx")
        
        # 验证
        self.assertEqual(len(images), 2)
        # 验证是否过滤了非图片和排序
        self.assertTrue(any(img[0].startswith(b'fake_png') for img in images))
        self.assertTrue(any(img[0].startswith(b'fake_jpg') for img in images))
        
        # 验证页码是否为 0
        self.assertEqual(images[0][1], 0)

if __name__ == '__main__':
    unittest.main()
