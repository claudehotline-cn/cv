
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import sys
from pathlib import Path

# 添加项目跟目录到 path
sys.path.insert(0, str(Path(__file__).parents[2]))

from rag_service.services.vlm_service import VLMService

class TestChartQA(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_chart(self):
        # Mock settings
        with patch('rag_service.services.vlm_service.settings') as mock_settings:
            mock_settings.vlm_model = "qwen3-vl:30b"
            mock_settings.ollama_base_url = "http://localhost:11434"
            
            service = VLMService()
            
            # Mock analyze_image to return simulated JSON response
            service.analyze_image = AsyncMock()
            service.analyze_image.return_value = MagicMock(
                content='''```json
{
    "data": {"x": [1, 2, 3], "y": [10, 20, 30]},
    "analysis": "Rising trend",
    "conclusion": "Growth observed"
}
```'''
            )
            
            # Call analyze_chart
            response = await service.analyze_chart(b"fake_image_data")
            
            # Verify analyze_image was called with correct prompt
            service.analyze_image.assert_called_once()
            args, _ = service.analyze_image.call_args
            assert args[0] == b"fake_image_data"
            assert "专为图表深度分析" in args[1] or "提取数据" in args[1]
            
            # Verify response content
            self.assertIn("Rising trend", response.content)

if __name__ == '__main__':
    unittest.main()
