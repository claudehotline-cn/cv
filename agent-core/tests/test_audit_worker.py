import pytest
import asyncio
from unittest.mock import MagicMock, patch
from agent_core.workers.audit import AuditWorker
from agent_core.events import EventBus

class MockEventBus(EventBus):
    def __init__(self, events):
        self.events = events
        
    async def publish(self, topic: str, event: dict) -> None:
        pass
        
    async def subscribe(self, topic: str, last_id: str = "$"):
        for event in self.events:
            yield event
            # Simulate async yield
            await asyncio.sleep(0.01)

@pytest.mark.asyncio
async def test_audit_worker_consumes_events():
    """Test that AuditWorker consumes and logs events."""
    
    # Setup
    test_events = [
        {"type": "tool_start", "data": {"tool": "test_tool"}},
        {"type": "tool_end", "data": {"output": "result"}}
    ]
    bus = MockEventBus(test_events)
    worker = AuditWorker(bus)
    
    # Mock stdout to verify logging
    with patch("builtins.print") as mock_print:
        # Run worker (it stops when iterator is exhausted if designed so, or we cancel)
        # Actually our MockEventBus yields finite events then stops.
        # But AuditWorker loop `async for` will finish when iterator finishes.
        await worker.start()
        
        # Verify
        assert mock_print.call_count == 2
        
        # Check first log
        args, _ = mock_print.call_args_list[0]
        log_str = args[0]
        assert "AUDIT_LOG:" in log_str
        assert "tool_start" in log_str
