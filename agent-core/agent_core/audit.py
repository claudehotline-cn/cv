from typing import Any, Dict, List, Optional, Union
from uuid import UUID
import time
import logging
import asyncio
import uuid
from functools import wraps

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from .events import AuditEmitter

_LOGGER = logging.getLogger(__name__)

class AuditCallbackHandler(AsyncCallbackHandler):
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

    def _get_ids(self, kwargs: Dict[str, Any]):
        """
        Extract Request/Trace IDs according to New Architecture.

        config/metadata:
            request_id: Business Logic ID (agent_runs.run_id)
            run_id: Legacy Business Logic ID (Alias for request_id)
        
        kwargs:
            run_id: Trace/Span ID (Native LangChain UUID)
            parent_run_id: Parent Span ID (Native LangChain UUID)
        """
        md = self._md(kwargs)
        
        # 1. Request ID (Business Run)
        # This is the FK linking this Span to the User Task
        request_id = md.get("request_id") or md.get("run_id") or "unknown"
        
        # 2. Span ID (Trace Node)
        # Native LangChain ID. This is the primary key of agent_spans.
        span_id = str(kwargs.get("run_id"))
        
        # 3. Parent Span ID (Trace Edge)
        parent_span_id = str(kwargs.get("parent_run_id")) if kwargs.get("parent_run_id") else None
        
        session_id = str(md.get("session_id")) if md.get("session_id") else None
        thread_id = str(md.get("thread_id")) if md.get("thread_id") else None
        
        return request_id, span_id, parent_span_id, session_id, thread_id

    async def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any) -> Any:
        try:
            # New Architecture: Decoupled IDs
            request_id, span_id, parent_span_id, session_id, thread_id = self._get_ids(kwargs)
            md = self._md(kwargs)
            
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
                
            name = kwargs.get("name") or md.get("name")

            # Cache context for end/error events which might lack metadata
            # Key off the SPAN_ID (Native LC ID)
            self._run_context[span_id] = {
                "request_id": request_id,
                "session_id": session_id,
                "thread_id": thread_id,
                "is_agent": is_agent,
                "agent_name": agent_name,
                "name": name,
                "langgraph_node": md.get("langgraph_node"),
                "subagent": md.get("sub_agent")
            }

            # Emit run_started ONCE per Request ID
            # This mimics the "Root Span" creation for the Business Run
            if request_id != "unknown" and request_id not in self._seen_runs:
                self._seen_runs.add(request_id)
                await self.emitter.emit(
                    event_type="run_started", 
                    request_id=request_id, # Business ID
                    session_id=session_id,
                    thread_id=thread_id,
                    span_id=None, # Run event has no span
                    component="agent", 
                    payload={
                        "root_agent_name": agent_name
                    }
                )
            
            # Pure Trace Event
            event_type = "chain_start"
            if component == "agent":
                event_type = "subagent_started"
            elif md.get("langgraph_node"):
                # Explicitly detect LangGraph Nodes
                event_type = "langgraph_node_started"
                component = "node"
                
            await self.emitter.emit(
                event_type=event_type, 
                request_id=request_id,       # Links to AgentRun (FK)
                span_id=span_id,         # PK of AgentSpan
                parent_span_id=parent_span_id, # Tree Structure
                session_id=session_id,
                thread_id=thread_id,
                component=component, 
                payload={
                    "inputs_digest": str(self._sanitize_inputs(inputs))[:2000],
                    "name": name,
                    "langgraph_node": md.get("langgraph_node"),
                    "subagent": md.get("sub_agent")
                }
            )
        except Exception as e:
            import traceback
            print(f"[AuditError] CRASH in on_chain_start: {e}\n{traceback.format_exc()}", flush=True)
            pass

    async def on_chain_end(self, outputs: Dict[str, Any], **kwargs: Any) -> Any:
        md = self._md(kwargs)
        # Native Span ID
        span_id = str(kwargs.get("run_id"))
        
        # Retrieve context
        ctx = self._run_context.get(span_id, {})
        request_id = ctx.get("request_id") or "unknown"
        session_id = ctx.get("session_id")
        thread_id = ctx.get("thread_id")
        
        event_type = "chain_end"
        component = "chain"
        if ctx.get("is_agent"):
            event_type = "subagent_finished"
            component = "agent"
        elif ctx.get("langgraph_node"):
            event_type = "langgraph_node_finished"
            component = "node"
            
        await self.emitter.emit(
            event_type=event_type, 
            request_id=request_id, 
            session_id=session_id,
            thread_id=thread_id,
            span_id=span_id, 
            component=component, 
            payload={
                "outputs_digest": str(self._sanitize_inputs(outputs))[:2000],
                "name": ctx.get("name"),
                "langgraph_node": ctx.get("langgraph_node"),
                "subagent": ctx.get("subagent")
            }
        )
        
        # Emit run_finished if this chain was the agent (Last mile updater for DB status)
        if ctx.get("is_agent"):
            await self.emitter.emit(
                event_type="run_finished", 
                request_id=request_id, 
                session_id=session_id,
                thread_id=thread_id,
                span_id=span_id, 
                component="agent",
                payload={"outputs_digest": str(self._sanitize_inputs(outputs))[:2000]}
            )
        
        # Cleanup
        self._run_context.pop(span_id, None)
        
    async def on_chain_error(self, error: Union[Exception, KeyboardInterrupt], **kwargs: Any) -> Any:
        # Native Span ID
        span_id = str(kwargs.get("run_id"))
        
        # Retrieve context
        ctx = self._run_context.get(span_id, {})
        request_id = ctx.get("request_id") or "unknown"
        session_id = ctx.get("session_id")
        thread_id = ctx.get("thread_id")

        error_type = type(error).__name__
        is_interrupt = "Interrupt" in error_type
        
        component = "chain"
        if ctx.get("langgraph_node"):
            component = "node"

        if is_interrupt:
            await self.emitter.emit(
                event_type="chain_interrupted", 
                request_id=request_id, 
                session_id=session_id,
                thread_id=thread_id,
                span_id=span_id, 
                component=component, 
                payload={
                    "error_class": error_type, 
                    "error_message": str(error)[:2000],
                    "name": ctx.get("name"),
                    "langgraph_node": ctx.get("langgraph_node"),
                    "subagent": ctx.get("subagent")
                }
            )
            
            if ctx.get("is_agent"):
                await self.emitter.emit(
                    event_type="run_interrupted",
                    request_id=request_id, 
                    session_id=session_id,
                    thread_id=thread_id,
                    span_id=span_id, 
                    component="agent",
                    payload={
                        "error_class": error_type, 
                        "error_message": str(error)[:2000]
                    }
                )
        else:
            event_type = "chain_failed"
            if component == "node":
                event_type = "node_failed" # Optional: if distinct event needed

            await self.emitter.emit(
                event_type=event_type, 
                request_id=request_id, 
                session_id=session_id,
                thread_id=thread_id,
                span_id=span_id, 
                component=component, 
                payload={
                    "error_class": error_type, 
                    "error_message": str(error)[:2000],
                    "name": ctx.get("name"),
                    "langgraph_node": ctx.get("langgraph_node"),
                    "subagent": ctx.get("subagent")
                }
            )
            
            if ctx.get("is_agent"):
                await self.emitter.emit(
                    event_type="run_failed", 
                    request_id=request_id, 
                    session_id=session_id,
                    thread_id=thread_id,
                    span_id=span_id, 
                    component="agent",
                    payload={
                        "error_class": error_type, 
                        "error_message": str(error)[:2000]
                    }
                )
        
        # Cleanup
        self._run_context.pop(span_id, None)

    async def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> Any:
        try:
            request_id, span_id, parent_span_id, session_id, thread_id = self._get_ids(kwargs)
            
            model_name = kwargs.get("invocation_params", {}).get("model_name", "unknown_model")

            # Cache context
            self._run_context[span_id] = {
                "request_id": request_id,
                "session_id": session_id,
                "thread_id": thread_id
            }
            
            await self.emitter.emit(
                event_type="llm_called", 
                request_id=request_id, 
                session_id=session_id,
                thread_id=thread_id,
                span_id=span_id, 
                parent_span_id=parent_span_id, 
                component="llm", 
                payload={
                    "model": model_name,
                    "prompts_digest": str(prompts)[:2000]
                }
            )
        except Exception:
            pass

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> Any:
        span_id = str(kwargs.get("run_id"))
        ctx = self._run_context.get(span_id, {})
        request_id = ctx.get("request_id") or "unknown"
        session_id = ctx.get("session_id")
        thread_id = ctx.get("thread_id")
        
        generations = []
        if response.generations:
            for g_list in response.generations:
                for g in g_list:
                    generations.append(g.text)
                    
        await self.emitter.emit(
            event_type="llm_output_received", 
            request_id=request_id, 
            session_id=session_id,
            thread_id=thread_id,
            span_id=span_id, 
            component="llm", 
            payload={
                "generations_digest": str(generations)[:2000],
                "token_usage": response.llm_output.get("token_usage") if response.llm_output else None
            }
        )
        
        self._run_context.pop(span_id, None)

    async def on_llm_error(self, error: Union[Exception, KeyboardInterrupt], **kwargs: Any) -> Any:
        span_id = str(kwargs.get("run_id"))
        ctx = self._run_context.get(span_id, {})
        request_id = ctx.get("request_id") or "unknown"
        session_id = ctx.get("session_id")
        thread_id = ctx.get("thread_id")
        
        await self.emitter.emit(
            event_type="llm_failed", 
            request_id=request_id, 
            session_id=session_id,
            thread_id=thread_id,
            span_id=span_id, 
            component="llm", 
            payload={
                "failure_domain": "llm", 
                "error_class": type(error).__name__, 
                "error_message": str(error)[:2000]
            }
        )
        
        self._run_context.pop(span_id, None)

    async def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """"""
        md = kwargs.get("metadata", {}) or {}
        if metadata:
            md.update(metadata)
        
        request_id = md.get("request_id") or md.get("run_id") or "unknown"
        lc_span_id = str(run_id)
        # Check metadata['span_id'] from node_wrapper, else use parent_run_id
        parent_span_id = str(parent_run_id) if parent_run_id else None
        if md.get("span_id"):
             parent_span_id = md.get("span_id")
        
        tool_name = serialized.get("name") if serialized else "unknown"
        
        session_id = str(md.get("session_id")) if md.get("session_id") else None
        thread_id = str(md.get("thread_id")) if md.get("thread_id") else None

        # Cache context
        self._run_context[lc_span_id] = {
            "request_id": request_id, 
            "session_id": session_id,
            "thread_id": thread_id,
            "tool_name": tool_name
        }

        await self.emitter.emit(
            event_type="tool_call_requested", 
            request_id=request_id, 
            session_id=session_id,
            thread_id=thread_id,
            span_id=lc_span_id, 
            parent_span_id=parent_span_id,
            component="tool", 
            payload={
                "tool_name": tool_name, 
                "input_digest": str(input_str)[:2000]
            }
        )

    async def on_tool_end(self, output: str, **kwargs: Any) -> Any:
        span_id = str(kwargs.get("run_id"))
        ctx = self._run_context.get(span_id, {})
        request_id = ctx.get("request_id") or "unknown"
        session_id = ctx.get("session_id")
        thread_id = ctx.get("thread_id")
        tool_name = ctx.get("tool_name", "unknown")
        
        # Semantic Error Detection
        is_error = False
        error_msg = None
        
        try:
            import json
            if "{" in output and "}" in output:
                data = json.loads(output)
                if isinstance(data, dict):
                    if data.get("success") is False:
                        is_error = True
                        error_msg = data.get("error") or data.get("message") or str(data)
                    elif "error" in data and data["error"]:
                        is_error = True
                        error_msg = data["error"]
        except:
            pass
            
        if not is_error and isinstance(output, str) and output.strip().startswith("Error:"):
            is_error = True
            error_msg = output
            
        if is_error:
            await self.emitter.emit(
                event_type="tool_failed", 
                request_id=request_id, 
                session_id=session_id,
                thread_id=thread_id,
                span_id=span_id, 
                component="tool", 
                payload={
                    "failure_domain": "tool", 
                    "error_class": "SemanticError", 
                    "error_message": str(error_msg)[:2000],
                    "tool_name": tool_name,
                    "output_digest": str(output)[:2000] 
                }
            )
        else:
            await self.emitter.emit(
                event_type="tool_call_executed", 
                request_id=request_id, 
                session_id=session_id,
                thread_id=thread_id,
                span_id=span_id, 
                component="tool", 
                payload={
                    "output_digest": str(output)[:2000],
                    "tool_name": tool_name
                }
            )
        
        self._run_context.pop(span_id, None)

    async def on_tool_error(self, error: Union[Exception, KeyboardInterrupt], **kwargs: Any) -> Any:
        span_id = str(kwargs.get("run_id"))
        ctx = self._run_context.get(span_id, {})
        request_id = ctx.get("request_id") or "unknown"
        session_id = ctx.get("session_id")
        thread_id = ctx.get("thread_id")
        tool_name = ctx.get("tool_name", "unknown")
        
        await self.emitter.emit(
            event_type="tool_failed", 
            request_id=request_id, 
            session_id=session_id,
            thread_id=thread_id,
            span_id=span_id, 
            component="tool", 
            payload={
                "failure_domain": "tool", 
                "error_class": type(error).__name__, 
                "error_message": str(error)[:2000],
                "tool_name": tool_name
            }
        )
        
        self._run_context.pop(span_id, None)
        
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
