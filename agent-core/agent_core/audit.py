from typing import Any, Dict, List, Optional, Union
from uuid import UUID
import time
import logging
import asyncio

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from .events import EventBus

_LOGGER = logging.getLogger(__name__)

class AuditCallbackHandler(BaseCallbackHandler):
    """
    Callback Handler that captures Agent execution events and publishes them 
    to an Event Bus for asynchronous auditing.
    
    Captures:
    - on_tool_start: Inputs, arguments
    - on_tool_end: Outputs, status
    - on_tool_error: Error details
    - on_chain_end: Final response (if applicable)
    """
    
    def __init__(self, event_bus: EventBus, user_id: str = "unknown", trace_id: str = "unknown"):
        super().__init__()
        self.event_bus = event_bus
        self.user_id = user_id
        self.trace_id = trace_id
        self.channel = "agent:audit_events"
        
    def _publish_event(self, event_type: str, payload: Dict[str, Any]):
        """Publish event to Redis Stream (fire and forget)."""
        event = {
            "type": event_type,
            "timestamp": time.time(),
            "user_id": self.user_id,
            "trace_id": self.trace_id,
            "data": payload
        }
        
        # We need to run/schedule the async publish method from this sync/async callback.
        # LangChain callbacks can be sync or async. 
        # If we are in an async loop, we should use create_task.
        
        try:
            # Check if there is a running loop
            loop = asyncio.get_running_loop()
            loop.create_task(self.event_bus.publish(self.channel, event))
        except RuntimeError:
            # No running loop (sync context), we might lose events or need sync publish.
            # For Agent Platform, we assume Async Runtime.
            _LOGGER.warning(f"[Audit] No running event loop, skipping audit event: {event_type}")

    async def on_tool_start(
        self, serialized: Dict[str, Any], input_str: str, **kwargs: Any
    ) -> Any:
        """Run when tool starts running."""
        tool_name = serialized.get("name")
        self._publish_event("tool_start", {
            "tool": tool_name,
            "input": input_str,
            "run_id": str(kwargs.get("run_id", ""))
        })

    async def on_tool_end(self, output: str, **kwargs: Any) -> Any:
        """Run when tool ends running."""
        tool_name = kwargs.get("name", "unknown_tool")
        self._publish_event("tool_end", {
            "tool": tool_name,
            "output": output,
            "run_id": str(kwargs.get("run_id", ""))
        })

    async def on_tool_error(
        self, error: Union[Exception, KeyboardInterrupt], **kwargs: Any
    ) -> Any:
        """Run when tool errors."""
        self._publish_event("tool_error", {
            "error": str(error),
            "run_id": str(kwargs.get("run_id", ""))
        })
