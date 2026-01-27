import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from agent_core.workers.audit import AuditWorker
 

class MockEventBus:
    def __init__(self, events):
        self.events = events
        
    async def subscribe(self, topic: str, last_id: str = "$"):
        for event in self.events:
            yield event
            # Simulate async yield
            await asyncio.sleep(0.01)

def test_audit_worker_consumes_events_and_calls_persist_callback():
     
    async def run():
        test_events = [
            {"type": "tool_start", "data": {"tool": "test_tool"}},
            {"type": "tool_end", "data": {"output": "result"}},
        ]
        bus = MockEventBus(test_events)
        persist_cb = AsyncMock()
        worker = AuditWorker(bus, persist_callback=persist_cb)

        with patch("builtins.print"):
            await worker.start()

        assert persist_cb.await_count >= 1
        batch = persist_cb.await_args.args[0]
        assert isinstance(batch, list)
        assert len(batch) == 2

    asyncio.run(run())
