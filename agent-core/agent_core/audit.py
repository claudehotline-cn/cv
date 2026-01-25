from typing import Any, Dict, List, Optional, Union
from uuid import UUID
import time
import logging
import asyncio
import uuid
from functools import wraps

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from .events import AuditEmitter

_LOGGER = logging.getLogger(__name__)

class AuditCallbackHandler(BaseCallbackHandler):
    """
    Callback Handler that captures Agent execution events and emits them 
    via AuditEmitter for asynchronous auditing.
    """
    
    def __init__(self, emitter: AuditEmitter):
        super().__init__()
        self.emitter = emitter
        self._run_context: Dict[str, Dict[str, Any]] = {}
        self._seen_runs: set = set()
        
    def _md(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Extract metadata safely."""
        return kwargs.get("metadata", {}) or {}

    async def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any) -> Any:
        md = self._md(kwargs)
        lc_run_id = str(kwargs.get("run_id")) if kwargs.get("run_id") else None
        lc_parent_id = str(kwargs.get("parent_run_id")) if kwargs.get("parent_run_id") else None
        
        # Determine component type and agent name
        component = "chain"
        is_agent = False
        agent_name = "unknown"
        
        tags = md.get("tags") or kwargs.get("tags", [])
        
        # Heuristic to find agent name
        for tag in tags:
            if tag.startswith("agent:") and tag != "agent":
                agent_name = tag.split(":", 1)[1]
                is_agent = True
                break
            if tag.endswith("_agent"):
                agent_name = tag
                is_agent = True
        
        # Fallback to metadata
        if agent_name == "unknown" and md.get("agent_name"):
            agent_name = md.get("agent_name")
            is_agent = True
            
        if "agent" in tags or is_agent:
            component = "agent"
        
        # Check sub_agent metadata
        if md.get("sub_agent"):
            agent_name = md.get("sub_agent")
            # If it's a subagent, we might treat it as agent component too?
            # But usually 'agent' tag is sufficient.
            
        # Extract IDs
        run_id = str(md.get("run_id")) if md.get("run_id") else "unknown"
        session_id = str(md.get("session_id")) if md.get("session_id") else None
        thread_id = str(md.get("thread_id")) if md.get("thread_id") else None

        # Cache context for end/error events which might lack metadata
        if lc_run_id:
            self._run_context[lc_run_id] = {
                "run_id": run_id,
                "session_id": session_id,
                "thread_id": thread_id,
                "is_agent": is_agent,
                "agent_name": agent_name
            }

        # Emit run_started if we haven't seen this run_id yet AND it is an agent
        # (Only start Run for the Agent, not every chain, unless run_id is new)
        # Actually, run_id maps to AgentRun. Only one AgentRun per session usually? 
        # No, multiple turns. Each turn has unique run_id.
        if run_id != "unknown" and run_id not in self._seen_runs:
            self._seen_runs.add(run_id)
            await self.emitter.emit(
                event_type="run_started", 
                run_id=run_id, 
                session_id=session_id,
                thread_id=thread_id,
                span_id=lc_run_id, 
                component="agent", 
                payload={
                    "inputs_digest": str(self._sanitize_inputs(inputs))[:2000],
                    "root_agent_name": agent_name
                }
            )
            
        await self.emitter.emit(
            event_type="chain_start", 
            run_id=run_id, 
            session_id=session_id,
            thread_id=thread_id,
            span_id=lc_run_id,
            parent_span_id=lc_parent_id,
            component=component, 
            payload={
                "inputs_digest": str(self._sanitize_inputs(inputs))[:2000],
                "name": kwargs.get("name") or md.get("name"),
                "langgraph_node": md.get("langgraph_node"),
                "subagent": md.get("sub_agent")
            }
        )

    async def on_chain_end(self, outputs: Dict[str, Any], **kwargs: Any) -> Any:
        md = self._md(kwargs)
        lc_run_id = str(kwargs.get("run_id")) if kwargs.get("run_id") else None
        
        # Retrieve context
        ctx = self._run_context.get(lc_run_id, {}) if lc_run_id else {}
        run_id = ctx.get("run_id") or (str(md.get("run_id")) if md.get("run_id") else "unknown")
        session_id = ctx.get("session_id") or (str(md.get("session_id")) if md.get("session_id") else None)
        thread_id = ctx.get("thread_id") or (str(md.get("thread_id")) if md.get("thread_id") else None)
        
        await self.emitter.emit(
            event_type="chain_end", 
            run_id=run_id, 
            session_id=session_id,
            thread_id=thread_id,
            span_id=lc_run_id, 
            component="chain", 
            payload={"outputs_digest": str(self._sanitize_inputs(outputs))[:2000]}
        )
        
        # Emit run_finished if this chain was the agent
        if ctx.get("is_agent"):
            await self.emitter.emit(
                event_type="run_finished", 
                run_id=run_id, 
                session_id=session_id,
                thread_id=thread_id,
                span_id=lc_run_id, 
                component="agent",
                payload={"outputs_digest": str(self._sanitize_inputs(outputs))[:2000]}
            )
        
        # Cleanup
        if lc_run_id:
            self._run_context.pop(lc_run_id, None)
        
    async def on_chain_error(self, error: Union[Exception, KeyboardInterrupt], **kwargs: Any) -> Any:
        md = self._md(kwargs)
        lc_run_id = str(kwargs.get("run_id")) if kwargs.get("run_id") else None
        
        # Retrieve context
        ctx = self._run_context.get(lc_run_id, {}) if lc_run_id else {}
        run_id = ctx.get("run_id") or (str(md.get("run_id")) if md.get("run_id") else "unknown")
        session_id = ctx.get("session_id") or (str(md.get("session_id")) if md.get("session_id") else None)
        thread_id = ctx.get("thread_id") or (str(md.get("thread_id")) if md.get("thread_id") else None)

        await self.emitter.emit(
            event_type="chain_failed", 
            run_id=run_id, 
            session_id=session_id,
            thread_id=thread_id,
            span_id=lc_run_id, 
            component="chain", 
            payload={
                "error_class": type(error).__name__, 
                "error_message": str(error)[:2000]
            }
        )
        
        # Emit run_failed if this chain was the agent
        if ctx.get("is_agent"):
            await self.emitter.emit(
                event_type="run_failed", 
                run_id=run_id, 
                session_id=session_id,
                thread_id=thread_id,
                span_id=lc_run_id, 
                component="agent",
                payload={
                    "error_class": type(error).__name__, 
                    "error_message": str(error)[:2000]
                }
            )
        
        # Cleanup
        if lc_run_id:
            self._run_context.pop(lc_run_id, None)

    async def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> Any:
        md = self._md(kwargs)
        lc_run_id = str(kwargs.get("run_id")) if kwargs.get("run_id") else None
        lc_parent_id = str(kwargs.get("parent_run_id")) if kwargs.get("parent_run_id") else None
        
        model_name = kwargs.get("invocation_params", {}).get("model_name", "unknown_model")
        
        session_id = str(md.get("session_id")) if md.get("session_id") else None
        thread_id = str(md.get("thread_id")) if md.get("thread_id") else None

        # Cache context
        if lc_run_id:
            self._run_context[lc_run_id] = {
                "run_id": str(md.get("run_id")) if md.get("run_id") else "unknown",
                "session_id": session_id,
                "thread_id": thread_id
            }
        
        await self.emitter.emit(
            event_type="llm_called", 
            run_id=str(md.get("run_id")) if md.get("run_id") else "unknown", 
            session_id=session_id,
            thread_id=thread_id,
            span_id=lc_run_id, 
            parent_span_id=lc_parent_id, 
            component="llm", 
            payload={
                "model": model_name,
                "prompts_digest": str(prompts)[:2000]
            }
        )

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> Any:
        md = self._md(kwargs)
        lc_run_id = str(kwargs.get("run_id")) if kwargs.get("run_id") else None
        
        # Retrieve context
        ctx = self._run_context.get(lc_run_id, {}) if lc_run_id else {}
        run_id = ctx.get("run_id") or (str(md.get("run_id")) if md.get("run_id") else "unknown")
        session_id = ctx.get("session_id") or (str(md.get("session_id")) if md.get("session_id") else None)
        thread_id = ctx.get("thread_id") or (str(md.get("thread_id")) if md.get("thread_id") else None)
        
        generations = []
        if response.generations:
            for g_list in response.generations:
                for g in g_list:
                    generations.append(g.text)
                    
        await self.emitter.emit(
            event_type="llm_output_received", 
            run_id=run_id, 
            session_id=session_id,
            thread_id=thread_id,
            span_id=lc_run_id, 
            component="llm", 
            payload={
                "generations_digest": str(generations)[:2000],
                "token_usage": response.llm_output.get("token_usage") if response.llm_output else None
            }
        )
        
        if lc_run_id:
            self._run_context.pop(lc_run_id, None)

    async def on_llm_error(self, error: Union[Exception, KeyboardInterrupt], **kwargs: Any) -> Any:
        md = self._md(kwargs)
        lc_run_id = str(kwargs.get("run_id")) if kwargs.get("run_id") else None
        
        # Retrieve context
        ctx = self._run_context.get(lc_run_id, {}) if lc_run_id else {}
        run_id = ctx.get("run_id") or (str(md.get("run_id")) if md.get("run_id") else "unknown")
        session_id = ctx.get("session_id") or (str(md.get("session_id")) if md.get("session_id") else None)
        thread_id = ctx.get("thread_id") or (str(md.get("thread_id")) if md.get("thread_id") else None)
        
        await self.emitter.emit(
            event_type="llm_failed", 
            run_id=run_id, 
            session_id=session_id,
            thread_id=thread_id,
            span_id=lc_run_id, 
            component="llm", 
            payload={
                "failure_domain": "llm", 
                "error_class": type(error).__name__, 
                "error_message": str(error)[:2000]
            }
        )
        
        if lc_run_id:
            self._run_context.pop(lc_run_id, None)

    async def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs: Any) -> Any:
        md = self._md(kwargs)
        lc_run_id = str(kwargs.get("run_id")) if kwargs.get("run_id") else None
        lc_parent_id = str(kwargs.get("parent_run_id")) if kwargs.get("parent_run_id") else None
        tool_name = serialized.get("name") if serialized else "unknown"
        
        session_id = str(md.get("session_id")) if md.get("session_id") else None
        thread_id = str(md.get("thread_id")) if md.get("thread_id") else None

        # Cache context
        if lc_run_id:
            self._run_context[lc_run_id] = {
                "run_id": str(md.get("run_id")) if md.get("run_id") else "unknown",
                "session_id": session_id,
                "thread_id": thread_id,
                "tool_name": tool_name
            }

        await self.emitter.emit(
            event_type="tool_call_requested", 
            run_id=str(md.get("run_id")) if md.get("run_id") else "unknown", 
            session_id=session_id,
            thread_id=thread_id,
            span_id=lc_run_id, 
            parent_span_id=lc_parent_id,
            component="tool", 
            payload={
                "tool_name": tool_name, 
                "input_digest": str(input_str)[:2000]
            }
        )

    async def on_tool_end(self, output: str, **kwargs: Any) -> Any:
        md = self._md(kwargs)
        lc_run_id = str(kwargs.get("run_id")) if kwargs.get("run_id") else None
        
        # Retrieve context
        ctx = self._run_context.get(lc_run_id, {}) if lc_run_id else {}
        run_id = ctx.get("run_id") or (str(md.get("run_id")) if md.get("run_id") else "unknown")
        session_id = ctx.get("session_id") or (str(md.get("session_id")) if md.get("session_id") else None)
        thread_id = ctx.get("thread_id") or (str(md.get("thread_id")) if md.get("thread_id") else None)
        tool_name = ctx.get("tool_name", "unknown")
        
        await self.emitter.emit(
            event_type="tool_call_executed", 
            run_id=run_id, 
            session_id=session_id,
            thread_id=thread_id,
            span_id=lc_run_id, 
            component="tool", 
            payload={
                "output_digest": str(output)[:2000],
                "tool_name": tool_name
            }
        )
        
        if lc_run_id:
            self._run_context.pop(lc_run_id, None)

    async def on_tool_error(self, error: Union[Exception, KeyboardInterrupt], **kwargs: Any) -> Any:
        md = self._md(kwargs)
        lc_run_id = str(kwargs.get("run_id")) if kwargs.get("run_id") else None
        
        # Retrieve context
        ctx = self._run_context.get(lc_run_id, {}) if lc_run_id else {}
        run_id = ctx.get("run_id") or (str(md.get("run_id")) if md.get("run_id") else "unknown")
        session_id = ctx.get("session_id") or (str(md.get("session_id")) if md.get("session_id") else None)
        thread_id = ctx.get("thread_id") or (str(md.get("thread_id")) if md.get("thread_id") else None)
        tool_name = ctx.get("tool_name", "unknown")
        
        await self.emitter.emit(
            event_type="tool_failed", 
            run_id=run_id, 
            session_id=session_id,
            thread_id=thread_id,
            span_id=lc_run_id, 
            component="tool", 
            payload={
                "failure_domain": "tool", 
                "error_class": type(error).__name__, 
                "error_message": str(error)[:2000],
                "tool_name": tool_name
            }
        )
        
        if lc_run_id:
            self._run_context.pop(lc_run_id, None)
        
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
        if hasattr(inputs, "dict"):
            return self._sanitize_inputs(inputs.dict())
        if hasattr(inputs, "to_json"):
            return inputs.to_json()
        if isinstance(inputs, str):
            if len(inputs) > 5000:
                return inputs[:5000] + "...[TRUNCATED]"
            return inputs
        if not isinstance(inputs, (str, int, float, bool)):
            return str(inputs)
        return inputs
