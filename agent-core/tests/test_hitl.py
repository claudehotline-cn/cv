import pytest
import os
import sys
from unittest.mock import MagicMock, patch
from langchain_core.messages import ToolMessage
from langgraph.types import interrupt

# Patch interrupt to just return a mock value (simulating user resumed with this value)
# or capture the interrupt call. 
# Since we want to test the middleware logic flow, we need to mock `interrupt`.

from agent_core.middleware import SensitiveToolMiddleware

@pytest.mark.asyncio
async def test_hitl_interrupt_trigger():
    """Test that middleware interrupts on sensitive tool."""
    
    # Setup
    middleware = SensitiveToolMiddleware(sensitive_tools=["delete_file"])
    
    # Mock Request
    class MockRequest:
        tool_call = {"name": "delete_file", "args": {"path": "/tmp/a.txt"}, "id": "1"}
        
    # Mock Handler (should be called only if approved)
    mock_handler = AsyncMock(return_value="executed")
    
    # Mock langgraph.types.interrupt to return Approval
    # We strip 'agent_core.middleware' import of interrupt? No, it's imported in the module.
    # We need to patch where it is used.
    
    approval_payload = [{"type": "approve", "message": "Go ahead"}]
    
    with patch("agent_core.middleware.interrupt", return_value=approval_payload) as mock_interrupt:
        result = await middleware.awrap_tool_call(MockRequest(), mock_handler)
        
        # Verify Interrupt called
        mock_interrupt.assert_called_once()
        args = mock_interrupt.call_args[0][0]
        assert args["action_requests"][0]["name"] == "delete_file"
        
        # Verify Handler called (Approval flow)
        mock_handler.assert_called_once()
        assert result == "executed"

@pytest.mark.asyncio
async def test_hitl_rejection():
    """Test that Rejection stops execution."""
    middleware = SensitiveToolMiddleware(sensitive_tools=["delete_file"])
    
    class MockRequest:
        tool_call = {"name": "delete_file", "id": "1"}
        
    mock_handler = AsyncMock(return_value="executed")
    
    rejection_payload = [{"type": "reject", "message": "Too dangerous"}]
    
    with patch("agent_core.middleware.interrupt", return_value=rejection_payload):
        result = await middleware.awrap_tool_call(MockRequest(), mock_handler)
        
        # Verify Handler NOT called
        mock_handler.assert_not_called()
        
        # Verify specific Error Message returned
        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert "USER_INTERRUPT" in result.content
        assert "Too dangerous" in result.content

from unittest.mock import AsyncMock
