
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from rag_service.services.image_encoder import ImageEncoder

# 1x1 transparent PNG
VALID_IMAGE = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'

@pytest.fixture
def image_encoder():
    return ImageEncoder()

@pytest.mark.asyncio
async def test_encode_success(image_encoder):
    # Mock VLM service
    with patch('rag_service.services.image_encoder.vlm_service') as mock_vlm:
        mock_vlm.describe_image = AsyncMock(return_value="A cat sitting on a mat")
        
        # Mock Embedding service
        with patch('rag_service.services.image_encoder.embedding_service') as mock_embed:
            mock_embed.embed_text = MagicMock(return_value=[0.1, 0.2, 0.3])
            
            # Test data
            test_image = VALID_IMAGE
            
            embedding, description = await image_encoder.encode(test_image)
            
            assert description == "A cat sitting on a mat"
            assert embedding == [0.1, 0.2, 0.3]
            mock_vlm.describe_image.assert_called_once()
            mock_embed.embed_text.assert_called_once_with("A cat sitting on a mat")

def test_is_supported(image_encoder):
    assert image_encoder.is_supported("test.jpg") is True
    assert image_encoder.is_supported("test.png") is True
    assert image_encoder.is_supported("test.txt") is False
