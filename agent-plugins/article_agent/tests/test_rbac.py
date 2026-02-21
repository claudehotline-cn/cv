import pytest
import os
import sys
from unittest.mock import MagicMock
from langchain_core.messages import ToolMessage

# Mock generic environment
os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["AGENT_USER_ROLE"] = "guest"

# Mock dependencies similar to test_article_agent.py
sys.modules["minio"] = MagicMock()
sys.modules["minio.error"] = MagicMock()

# Import PolicyMiddleware (assuming it's in agent_core.middleware)
from agent_core.middleware import PolicyMiddleware

@pytest.mark.asyncio
async def test_policy_middleware_deny():
    """Test that Guest role is denied access to sensitive tools."""
    
    # Setup
    middleware = PolicyMiddleware(policy_path="policy.yaml")
    
    # Mock Handler that should NOT be called if denied
    mock_handler = MagicMock()
    
    # Mock Request
    class MockRequest:
        tool_call = {
            "name": "delete_file",
            "id": "call_123"
        }
        
    # Check DENY
    os.environ["AGENT_USER_ROLE"] = "guest" # Override
    result = await middleware.awrap_tool_call(MockRequest(), mock_handler)
    
    # Assert
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "PERMISSION DENIED" in result.content
    mock_handler.assert_not_called()

@pytest.mark.asyncio
async def test_policy_middleware_allow():
    """Test that Admin role is allowed access."""
    
    # Setup
    middleware = PolicyMiddleware(policy_path="policy.yaml")
    mock_handler = MagicMock()
    async def async_handler(req):
        return "Success"
    
    # Mock Request
    class MockRequest:
        tool_call = {
            "name": "delete_file",
            "id": "call_456"
        }
    
    # Check ALLOW
    os.environ["AGENT_USER_ROLE"] = "admin" # Override
    result = await middleware.awrap_tool_call(MockRequest(), async_handler)
    
    # Assert
    assert result == "Success"
