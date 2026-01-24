import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from agent_core.audit import AuditCallbackHandler
from agent_core.events import EventBus

class MockEventBus(EventBus):
    def __init__(self):
        self.published = []
        
    async def publish(self, topic: str, event: dict) -> None:
        self.published.append((topic, event))
        
    async def subscribe(self, topic: str, last_id: str = "$"):
        yield {}

@pytest.mark.asyncio
async def test_audit_callback_tool_lifecycle():
    """Test that AuditCallbackHandler publishes events on tool start/end."""
    
    # Setup
    bus = MockEventBus()
    handler = AuditCallbackHandler(event_bus=bus, user_id="test_user", trace_id="trace_123")
    
    # Simulate Tool Start
    await handler.on_tool_start(
        serialized={"name": "test_tool"},
        input_str="test input",
        run_id="run_abc"
    )
    
    # Simulate Tool End
    await handler.on_tool_end(
        output="test output",
        name="test_tool",
        run_id="run_abc"
    )
    
    # Wait for async tasks to complete (since publish is fired as create_task)
    # We yield control to loop
    await asyncio.sleep(0.1)
    
    # Assert
    assert len(bus.published) == 2
    
    start_event = bus.published[0][1]
    assert start_event["type"] == "tool_start"
    assert start_event["user_id"] == "test_user"
    assert start_event["data"]["tool"] == "test_tool"
    
    end_event = bus.published[1][1]
    assert end_event["type"] == "tool_end"
    assert end_event["data"]["output"] == "test output"

@pytest.mark.asyncio
async def test_audit_callback_full_tracing():
    """Test that AuditCallbackHandler captures Chain and LLM events."""
    from langchain_core.outputs import LLMResult, Generation
    
    bus = MockEventBus()
    handler = AuditCallbackHandler(event_bus=bus)
    
    # 1. Chain Start (Inputs)
    await handler.on_chain_start(
        serialized={"name": "test_chain"},
        inputs={"input": "hello"},
        run_id="chain_run"
    )
    
    # 2. LLM Start (Prompts)
    await handler.on_llm_start(
        serialized={},
        prompts=["User: hello"],
        invocation_params={"model_name": "gpt-4"},
        run_id="llm_run"
    )
    
    # 3. LLM End (Generations)
    await handler.on_llm_end(
        response=LLMResult(generations=[[Generation(text="Hi there")]]),
        run_id="llm_run"
    )
    
    # 4. Chain End (Outputs)
    await handler.on_chain_end(
        outputs={"output": "Hi there"},
        run_id="chain_run"
    )
    
    await asyncio.sleep(0.1)
    
    assert len(bus.published) == 4
    types = [e[1]["type"] for e in bus.published]
    assert types == ["chain_start", "llm_start", "llm_end", "chain_end"]
    
    # Verify Content
    assert bus.published[0][1]["data"]["inputs"]["input"] == "hello"
    assert bus.published[1][1]["data"]["prompts"][0] == "User: hello"
    assert bus.published[2][1]["data"]["generations"][0] == "Hi there"

