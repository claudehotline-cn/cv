
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from rag_service.main import app
import json

client = TestClient(app)

# 有效的 1x1 PNG 数据
VALID_IMAGE_BYTES = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'

def get_or_create_kb():
    """获取或创建一个测试知识库"""
    # 尝试创建
    response = client.post("/api/knowledge-bases", json={
        "name": "integration_test_kb",
        "description": "Created by integration tests",
        "chunk_size": 500,
        "chunk_overlap": 50
    })
    
    if response.status_code == 200:
        return response.json()['id']
    elif response.status_code == 400:
        # 已存在，查找 ID
        response = client.get("/api/knowledge-bases")
        items = response.json()['items']
        for item in items:
            if item['name'] == "integration_test_kb":
                return item['id']
    
    pytest.fail("Failed to get or create knowledge base")

def test_upload_image_flow():
    kb_id = get_or_create_kb()
    
    # Mock ImageEncoder.encode correctly by patching the class method where it's defined
    with patch('rag_service.services.image_encoder.ImageEncoder.encode', new_callable=AsyncMock) as mock_encode:
        # Mock return: (embedding, description)
        mock_encode.return_value = ([0.1] * 1024, "A test image description")
        
        # Mock MinIO upload (optional, but good for speed)
        with patch('rag_service.services.minio_service.MinIOService.upload_file') as mock_upload:
            mock_upload.return_value = f"kb_{kb_id}/images/test.png"
            
            # 准备上传文件
            files = {
                'file': ('test.png', VALID_IMAGE_BYTES, 'image/png')
            }
            
            response = client.post(f"/api/knowledge-bases/{kb_id}/upload-image", files=files)
            
            assert response.status_code == 200
            data = response.json()
            assert data['filename'] == 'test.png'
            assert data['status'] == 'processing'
            assert 'document_id' in data
