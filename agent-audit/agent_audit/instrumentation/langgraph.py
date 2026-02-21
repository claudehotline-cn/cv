from typing import Any, Callable, Dict, Optional, Union
import time
import uuid
import logging
from functools import wraps

from ..emitter import AuditEmitter

_LOGGER = logging.getLogger(__name__)

def with_span(config: Dict[str, Any], *, graph_id: str = "unknown", node_id: str = "unknown") -> Dict[str, Any]:
    md = dict(config.get("metadata", {}))
    
    # LangGraph Nodes are just Python functions, they do NOT have a native LangChain run_id yet.
    # We MUST generate a unique Span ID for this node execution here manually.
    span_id = str(uuid.uuid4())
    
    # Parent span is the parent_run_id from config (if available) - this is correct.
    # It might come from the parent Chain's execution context.
    parent_span_id = config.get("parent_run_id")

    md.update({
        "graph_id": graph_id,
        "node_id": node_id,
        "parent_span_id": str(parent_span_id) if parent_span_id else None,
        "span_id": span_id, # Our generated Span ID
        
        # CRITICAL: Do NOT overwrite "request_id" (business ID) in metadata.
        # It is passed down from the top level.
    })
    
    new_cfg = dict(config)
    new_cfg["metadata"] = md
    
    # We set "run_id" in the new config to our generated Span ID.
    # This ensures that any SUB-CHAINS or TOOLS called inside this node
    # will see this Span ID as their "parent_run_id".
    #
    # UPDATE: We MUST NOT set "run_id" here, because it will be copied to child LLM calls,
    # forcing them to reuse the SAME ID, causing a collision (Node ID == LLM ID).
    # Instead, we rely on metadata["span_id"] (handled by audit.py) for linkage.
    # new_cfg["run_id"] = span_id
        
    return new_cfg

def _resolve_emitter(
    emitter: AuditEmitter | Callable[[Dict[str, Any]], AuditEmitter] | None,
    config: Dict[str, Any],
) -> AuditEmitter | None:
    if emitter is None:
        cfg_emitter = config.get("audit_emitter")
        if isinstance(cfg_emitter, AuditEmitter):
            return cfg_emitter

        md = config.get("metadata", {})
        md_emitter = md.get("audit_emitter") if isinstance(md, dict) else None
        if isinstance(md_emitter, AuditEmitter):
            return md_emitter

        # Most reliable: derive from callbacks (LangChain callback propagation survives
        # LangGraph config filtering, without storing non-serializable objects in metadata).
        cbs = config.get("callbacks")
        candidates = []
        if cbs is not None:
            if isinstance(cbs, list):
                candidates = cbs
            else:
                handlers = getattr(cbs, "handlers", None)
                if isinstance(handlers, list):
                    candidates = handlers
                else:
                    candidates = [cbs]

        for cb in candidates:
            cb_emitter = getattr(cb, "emitter", None)
            if isinstance(cb_emitter, AuditEmitter):
                return cb_emitter

        return None

    if callable(emitter):
        try:
            return emitter(config)
        except Exception as exc:
            _LOGGER.warning("Failed to resolve audit emitter from callable: %s", exc)
            return None

    return emitter


def node_wrapper(
    node_id: str,
    *,
    emitter: AuditEmitter | Callable[[Dict[str, Any]], AuditEmitter] | None = None,
    graph_id: str = "unknown",
):
    """
    Decorator for LangGraph nodes to inject Span ID and emit audit events.
    
    Usage:
        from agent_core.decorators import node_wrapper
        
        @node_wrapper("my_node", graph_id="my_graph")
        async def my_node(state, config):
            ...
    """
    import inspect
    
    def deco(fn):
        @wraps(fn)
        async def wrapper(state: Any, config: Dict[str, Any], *args: Any, **kwargs: Any) -> Any:
            # 1. Inject new Span Context
            config2 = with_span(config, graph_id=graph_id, node_id=node_id)
            resolved_emitter = _resolve_emitter(emitter, config2)
            md = config2["metadata"]
            
            t0 = time.time()
            
            # Use request_id as the Global Trace ID (DB run_id)
            request_id = md.get("request_id", "unknown")
            
            span_id = md.get("span_id")
            parent_span_id = md.get("parent_span_id")
            
            if not parent_span_id:
                # 1. Try direct keys (rarely populated by LC)
                parent_span_id = config.get("parent_run_id")
                
                # 2. Try callbacks (Standard LC propagation)
                if not parent_span_id:
                    cbs = config.get("callbacks")
                    if cbs:
                        # If it's a CallbackManager or list
                        if hasattr(cbs, "parent_run_id"):
                             parent_span_id = getattr(cbs, "parent_run_id", None)
                        elif isinstance(cbs, list):
                             for cb in cbs:
                                 if hasattr(cb, "parent_run_id"):
                                     parent_span_id = getattr(cb, "parent_run_id", None)
                                     if parent_span_id: break
            
            # fallback to run_id if interpreted as parent context
            if not parent_span_id:
                 # config['run_id'] in LangGraph often points to the parent span (the graph run)
                 cand = config.get("run_id")
                 if cand and cand != request_id:
                     parent_span_id = cand

            # Ensure it's not the same as the Run ID (Request ID) to avoid FK violation
            if parent_span_id == request_id:
                parent_span_id = None
            
            # 2. Emit Start Event
            session_id = md.get("session_id")
            if not session_id:
                session_id = config.get("configurable", {}).get("session_id", "")
                
            thread_id = md.get("thread_id")
            if not thread_id:
                thread_id = config.get("configurable", {}).get("thread_id", "")
            
            try:
                if resolved_emitter:
                    await resolved_emitter.emit(
                        event_type="langgraph_node_started",
                        request_id=request_id,
                        session_id=session_id,
                        thread_id=thread_id,
                        span_id=span_id,
                        parent_span_id=parent_span_id,
                        component="node",
                        payload={"graph_id": graph_id, "node_id": node_id},
                    )
            
                # 3. Execute Node (Handle Sync/Async)
                out = fn(state, config2, *args, **kwargs)
                if inspect.isawaitable(out):
                    out = await out
                
                # 4. Emit Finish Event
                latency_ms = int((time.time() - t0) * 1000)
                if resolved_emitter:
                    await resolved_emitter.emit(
                        event_type="langgraph_node_finished",
                        request_id=request_id,
                        session_id=session_id,
                        thread_id=thread_id,
                        span_id=span_id,
                        parent_span_id=parent_span_id,
                        component="node",
                        payload={
                            "graph_id": graph_id,
                            "node_id": node_id,
                            "latency_ms": latency_ms,
                        },
                    )
                return out
                
            except Exception as e:
                # 5. Emit Failure Event
                latency_ms = int((time.time() - t0) * 1000)
                if resolved_emitter:
                    await resolved_emitter.emit(
                        event_type="node_failed",
                        request_id=request_id,
                        session_id=session_id,
                        thread_id=thread_id,
                        span_id=span_id,
                        parent_span_id=parent_span_id,
                        component="node",
                        payload={
                            "failure_domain": "node",
                            "graph_id": graph_id,
                            "node_id": node_id,
                            "error_class": type(e).__name__,
                            "error_message": str(e)[:2000],
                            "latency_ms": latency_ms,
                        },
                    )
                raise
        return wrapper
    return deco
