from typing import Any, Dict, List, Optional, Union
from uuid import UUID
import time
import logging
import asyncio

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from .settings import get_settings
from .events import EventBus, RedisEventBus

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
        """Publish event to Redis Stream (fire and forget, thread-safe)."""
        _LOGGER.info(f"[AuditCallback] Publishing {event_type} to {self.channel}")
        event = {
            "type": event_type,
            "timestamp": time.time(),
            "user_id": self.user_id,
            "trace_id": self.trace_id,
            "data": payload
        }
        
        # 尝试使用主 Loop 发送。如果失败（跨线程），则使用临时连接。
        try:
            loop = asyncio.get_running_loop()
            # 即使获取到了 loop，如果 bus 绑定的 loop 不同，await bus.publish 也会报错。
            # 所以我们要在一个 task 中尝试执行。
            task = loop.create_task(self._safe_publish(event))
            
            # 可选：添加回调处理错误，但如果这里报错，通常意味着我们也无法处理了
            # task.add_done_callback(...)
        except RuntimeError:
            # Case 1: 没有运行中的 Loop (完全同步环境)
            # 使用 asyncio.run 启动临时 Loop 发送
            try:
                asyncio.run(self._publish_new_bus(event))
            except Exception as e:
                _LOGGER.error(f"[AuditCallback] Sync publish failed: {e}")

    async def _safe_publish(self, event):
        """尝试使用共享 Bus 发送，若遇 Loop 错误则回退到临时 Bus"""
        try:
            await self.event_bus.publish(self.channel, event)
        except (RuntimeError, asyncio.InvalidStateError, Exception) as e:
            # 捕获所有潜在的 Loop/Future 绑定错误
            # 注意：Future attached to a different loop 通常是 RuntimeError 或 InvalidStateError
            # 但为了保险，捕获 Exception 并在日志中记录（如果是其他错误也会被重试掩盖，但 Audit 最重要的是记录下来）
            if "loop" in str(e).lower() or "future" in str(e).lower() or "lock" in str(e).lower():
                 # _LOGGER.debug(f"[AuditCallback] Shared bus failed ({e}), using temp bus.")
                 await self._publish_new_bus(event)
            else:
                 _LOGGER.error(f"[AuditCallback] Publish error: {e}")

    async def _publish_new_bus(self, event):
         try:
             settings = get_settings()
             # 创建新的瞬时连接
             temp_bus = RedisEventBus(settings.redis_url)
             await temp_bus.publish(self.channel, event)
             await temp_bus.close()
         except Exception as e:
             _LOGGER.error(f"[AuditCallback] Temp bus publish failed: {e}")

    async def on_tool_start(
        self, serialized: Dict[str, Any], input_str: str, **kwargs: Any
    ) -> Any:
        """Run when tool starts running."""
        tool_name = serialized.get("name")
        self._publish_event("tool_start", {
            "tool": tool_name,
            "input": input_str,
            "run_id": str(kwargs.get("run_id", "")),
            "tags": kwargs.get("tags"),
            "metadata": kwargs.get("metadata"),
        })

    async def on_tool_end(self, output: str, **kwargs: Any) -> Any:
        """Run when tool ends running."""
        tool_name = kwargs.get("name", "unknown_tool")
        self._publish_event("tool_end", {
            "tool": tool_name,
            "output": output, 
            "run_id": str(kwargs.get("run_id", "")),
            "tags": kwargs.get("tags"),
            "metadata": kwargs.get("metadata"),
        })

    async def on_tool_error(
        self, error: Union[Exception, KeyboardInterrupt], **kwargs: Any
    ) -> Any:
        """Run when tool errors."""
        self._publish_event("tool_error", {
            "error": str(error),
            "run_id": str(kwargs.get("run_id", "")),
            "tags": kwargs.get("tags"),
            "metadata": kwargs.get("metadata"),
        })

    async def on_chain_start(
        self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any
    ) -> Any:
        """Run when chain starts running."""
        # Filter noise: Only log if it seems like a significant chain or root
        # logical "Task" start usually has 'messages' or 'input'
        serialized = serialized or {}
        chain_name = serialized.get("name") or (serialized.get("id") or [])[-1] if serialized.get("id") else "unknown_chain"
        
        self._publish_event("chain_start", {
            "chain": chain_name,
            "inputs": self._sanitize_inputs(inputs),
            "run_id": str(kwargs.get("run_id", "")),
            "tags": kwargs.get("tags"),
            "metadata": kwargs.get("metadata"),
        })

    async def on_chain_end(self, outputs: Dict[str, Any], **kwargs: Any) -> Any:
        """Run when chain ends running."""
        self._publish_event("chain_end", {
            "outputs": self._sanitize_inputs(outputs), # Re-use sanitize for outputs
            "run_id": str(kwargs.get("run_id", "")),
            "tags": kwargs.get("tags"),
            "metadata": kwargs.get("metadata"),
        })

    async def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any
    ) -> Any:
        """Run when LLM starts running."""
        self._publish_event("llm_start", {
            "model": kwargs.get("invocation_params", {}).get("model_name"),
            "prompts": prompts,
            "run_id": str(kwargs.get("run_id", "")),
            "tags": kwargs.get("tags"),
            "metadata": kwargs.get("metadata"),
        })

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> Any:
        """Run when LLM ends running."""
        text_generations = []
        if response.generations:
            for gen_list in response.generations:
                for gen in gen_list:
                    text_generations.append(gen.text)
                    
        self._publish_event("llm_end", {
            "generations": text_generations,
            "usage": response.llm_output.get("token_usage") if response.llm_output else None,
            "run_id": str(kwargs.get("run_id", "")),
            "tags": kwargs.get("tags"),
            "metadata": kwargs.get("metadata"),
        })

    def _sanitize_inputs(self, inputs: Any) -> Any:
        """Helper to sanitize extensive inputs/outputs."""
        if inputs is None:
            return None
        if isinstance(inputs, dict):
            return {k: self._sanitize_inputs(v) for k, v in inputs.items()}
        if isinstance(inputs, list):
            return [self._sanitize_inputs(v) for v in inputs if not isinstance(v, (bytes, bytearray))]
        if isinstance(inputs, (bytes, bytearray)):
            return "<binary_data>"
        # Handle LangChain BaseMessage or Pydantic models
        if hasattr(inputs, "dict"):
            return self._sanitize_inputs(inputs.dict())
        if hasattr(inputs, "to_json"):
            return inputs.to_json()
        
        # Basic trimming for massive strings
        if isinstance(inputs, str):
            if len(inputs) > 5000:
                return inputs[:5000] + "...[TRUNCATED]"
            return inputs
            
        # Fallback for other objects
        if not isinstance(inputs, (str, int, float, bool)):
            return str(inputs)
            
        return inputs
