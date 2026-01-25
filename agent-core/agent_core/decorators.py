from typing import Any, Dict, Optional, Union
import time
import uuid
import logging
from functools import wraps

from .events import AuditEmitter

_LOGGER = logging.getLogger(__name__)

def new_span_id() -> str:
    return str(uuid.uuid4())

def with_span(config: Dict[str, Any], *, graph_id: str = "unknown", node_id: str = "unknown") -> Dict[str, Any]:
    md = dict(config.get("metadata", {}))
    # Prefer existing span_id in metadata as parent (nested manual spans)
    # If not found, use the current LangChain run_id from config (linking to LangGraph node)
    parent_span_id = md.get("span_id")
    if not parent_span_id:
        parent_span_id = config.get("run_id")
        # Ensure it's a string
        if parent_span_id:
            parent_span_id = str(parent_span_id)

    span_id = new_span_id()
    md.update({
        "graph_id": graph_id,
        "node_id": node_id,
        "parent_span_id": parent_span_id,
        "span_id": span_id,
    })
    new_cfg = dict(config)
    new_cfg["metadata"] = md
    return new_cfg

def node_wrapper(node_id: str, *, emitter: AuditEmitter, graph_id: str = "unknown"):
    """
    Decorator for LangGraph nodes to inject Span ID and emit audit events.
    
    Usage:
        from agent_core.decorators import node_wrapper
        
        @node_wrapper("my_node", emitter=emitter, graph_id="my_graph")
        async def my_node(state, config):
            ...
    """
    import inspect

    def deco(fn):
        @wraps(fn)
        async def wrapper(state: Any, config: Dict[str, Any], *args: Any, **kwargs: Any) -> Any:
            # 1. Inject new Span Context
            config2 = with_span(config, graph_id=graph_id, node_id=node_id)
            md = config2["metadata"]
            # Debugging orphan source
            # print(f"[ORPHAN HUNT] node_wrapper called for '{node_id}'. Config keys: {list(config.keys())}", flush=True)
            
            t0 = time.time()
            
            run_id = md.get("run_id", "unknown")
            span_id = md.get("span_id")
            parent_span_id = md.get("parent_span_id")
            
            if not parent_span_id:
                parent_span_id = config.get("run_id")
            if not parent_span_id and run_id != "unknown":
                parent_span_id = run_id
            
            # 2. Emit Start Event
            session_id = md.get("session_id")
            if not session_id:
                session_id = config.get("configurable", {}).get("session_id", "")
                
            thread_id = md.get("thread_id")
            if not thread_id:
                thread_id = config.get("configurable", {}).get("thread_id", "")
            
            try:
                await emitter.emit(
                    event_type="langgraph_node_started",
                    run_id=run_id,
                    session_id=session_id,
                    thread_id=thread_id,
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                    component="node",
                    payload={"graph_id": graph_id, "node_id": node_id}
                )
            
                # 3. Execute Node (Handle Sync/Async)
                out = fn(state, config2, *args, **kwargs)
                if inspect.isawaitable(out):
                    out = await out
                
                # 4. Emit Finish Event
                latency_ms = int((time.time() - t0) * 1000)
                await emitter.emit(
                    event_type="langgraph_node_finished",
                    run_id=run_id,
                    session_id=session_id,
                    thread_id=thread_id,
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                    component="node",
                    payload={
                        "graph_id": graph_id, 
                        "node_id": node_id, 
                        "latency_ms": latency_ms
                    }
                )
                return out
                
            except Exception as e:
                # 5. Emit Failure Event
                latency_ms = int((time.time() - t0) * 1000)
                await emitter.emit(
                    event_type="node_failed",
                    run_id=run_id,
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
                        "latency_ms": latency_ms
                    }
                )
                raise
        return wrapper
    return deco
