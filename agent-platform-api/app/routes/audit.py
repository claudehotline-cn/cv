from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.db import get_db
from app.models.db_models import AuditLogModel

router = APIRouter(prefix="/audit", tags=["audit"])

class AuditLog(BaseModel):
    time: str
    session_id: Optional[str] = None
    trace_id: Optional[str] = None
    user_id: str
    type: str
    severity: str
    description: str
    initiator: str
    agent: Optional[str] = None
    node: Optional[str] = None
    details: Optional[dict] = None

@router.get("/", response_model=List[AuditLog])
async def get_audit_logs(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """
    Get audit logs from the real database.
    """
    stmt = select(AuditLogModel).order_by(desc(AuditLogModel.created_at)).limit(limit)
    result = await db.execute(stmt)
    db_logs = result.scalars().all()
    
    logs = []
    for log in db_logs:
        # safely extract fields from JSON data if present
        data = log.data or {}
        # Parse description based on event type
        event_type = log.event_type
        description = "No description"
        node_name = "-" 
        agent_name = "-"
        
        # Helper to extract a clean string name/identifier
        def get_name(inner_data, key, default):
            val = inner_data.get(key)
            if isinstance(val, str): return val
            return default

        # Helper to format node
        def format_node_name(name):
            if not name or name == "-": return "-"
            return name.replace("_", " ").title().replace("Tv", "TV").replace("Sql", "SQL").replace("Llm", "LLM")

        # Helper to safely parse inner data
        def parse_inner(d):
            if isinstance(d, dict): return d
            if isinstance(d, str):
                try:
                    import json
                    return json.loads(d)
                except:
                    return {}
            return {}

        # Helper to safely parse inner data
        def parse_inner_payload(d):
            p = d.get("data")
            if isinstance(p, dict): return p
            if isinstance(p, str):
                try:
                    import json
                    return json.loads(p)
                except:
                    return {}
            return {}

        # Check top-level metadata/tags first (from my core fix)
        # log.data is the Full Event. The payload is in log.data['data']
        payload = parse_inner_payload(data)
        
        tags = payload.get("tags") or []
        metadata = payload.get("metadata") or {}
        
        # Try to detect Agent name from metadata
        if metadata.get("agent_name"):
            agent_name = metadata.get("agent_name")
            
        # Sub-agent name from metadata -> Use as Node Name
        if metadata.get("sub_agent"):
            node_name = metadata.get("sub_agent")
            
            # Infer Main Agent from Sub-Agent if not explicitly set
            if agent_name == "-":
                sub = node_name.lower()
                if "sql" in sub or "python" in sub or "data" in sub or "report" in sub or "visualizer" in sub:
                     agent_name = "Data Agent"
        
        # If Agent still not found, check tags for 'agent:name' pattern
        if agent_name == "-" and tags:
            for tag in tags:
                if tag.startswith("agent:"):
                    raw_agent = tag.split(":", 1)[1]
                    # Map standard sub-agent tags to Data Agent
                    if raw_agent in ["sql_agent", "python_agent", "visualizer_agent", "report_agent", "reviewer_agent"]:
                        agent_name = "Data Agent"
                    else:
                        agent_name = raw_agent.replace("_", " ").title()
                    break

        # Override node_name if explicit node_label exists
        if metadata.get("node_label"):
            node_name = metadata.get("node_label")
        
        # Fallback: if user_id is generic, maybe agent_name is better initiator?
        # But we have separate Agent column now.

        if event_type == "tool_start":
            inner_payload = parse_inner(data.get("data"))
            # inner_payload is ensured to be a dict by parse_inner (returns {} on err)
            
            tool = get_name(inner_payload, "tool", "unknown tool")

            if tool == "task":
                input_str = inner_payload.get("input", "{}")
                try:
                    import json
                    args = {}
                    if isinstance(input_str, str):
                        if input_str.startswith("{"):
                            args = json.loads(input_str)
                    elif isinstance(input_str, dict):
                        args = input_str
                    
                    subagent = args.get("subagent_type")
                    if subagent:
                        node_name = format_node_name(subagent)
                        tool = "Task"
                        # Infer Agent if not already found from tags
                        if agent_name == "-":
                            if "agent" in subagent or subagent in ["sql_agent", "python_agent", "reviewer_agent", "visualizer_agent", "report_agent"]:
                                agent_name = "Data Agent"
                    else:
                        # Debug info
                         keys = list(args.keys()) if args else []
                         node_name = f"Task (Keys: {keys})"
                except Exception as e:
                     node_name = f"Task (Err)"
            else:
                 if tool != "unknown tool":
                    node_name = format_node_name(tool)
            
            description = f"Executing: {tool}"
        
        elif event_type == "tool_end":
            inner_payload = parse_inner(data.get("data"))
            tool = get_name(inner_payload, "tool", "tool")
            if tool == "task":
                tool = "Task"
            description = f"Completed: {tool}"
            
        elif event_type == "tool_error":
             description = "Tool execution failed"

        elif event_type == "llm_start":
            inner_payload = parse_inner(data.get("data"))
            model = get_name(inner_payload, "model", "LLM")
            if "/" in model: model = model.split("/")[-1]
            # Use Model Name but keep it readable. If usually empty/generic, use AI Inference
            node_name = model if model != "LLM" else "AI Inference"
            description = f"Querying {node_name}"
            
        elif event_type == "llm_end":
            inner_payload = parse_inner(data.get("data"))
            # Extracts model name if provided by callback handler
            model = get_name(inner_payload, "model", "LLM")
            if "/" in model: model = model.split("/")[-1]
            node_name = model if model != "LLM" else "AI Inference"
            tokens = 0
            usage = inner_payload.get("usage") or {}
            if isinstance(usage, dict):
                tokens = usage.get("total_tokens", 0)
            description = f"LLM generation complete ({tokens} tokens)"

        elif event_type == "chain_start":
            inner_payload = parse_inner(data.get("data"))
            chain = get_name(inner_payload, "chain", "Chain")
            
            # Map technical chain names to user-friendly concepts
            if chain in ["Chain", "unknown_chain", "RunnableSequence", "RunnableParallel"]:
                 node_name = "Workflow Step"
            else:
                 node_name = chain
            
            # Use LangGraph specific metadata if available (injected by some runtimes)
            if metadata.get("langgraph_node"):
                node_name = metadata.get("langgraph_node").title()

            description = f"Started {node_name}"
            
        elif event_type == "chain_end":
            inner_payload = parse_inner(data.get("data"))
            chain = get_name(inner_payload, "chain", "Chain")
            
            if chain in ["Chain", "unknown_chain", "RunnableSequence", "RunnableParallel"]:
                 node_name = "Workflow Step"
            else:
                 node_name = chain

            if metadata.get("langgraph_node"):
                node_name = metadata.get("langgraph_node").title()

            description = "Step completed"
        elif event_type == "session_created":
            description = "New session created"
        elif "description" in data:
             # Fallback if 'data' is flat or description is at top level?
             # 'data' matches log.data (the event). event usually doesn't have description at top.
             # but payload might.
             description = str(data.get("data", {}).get("description", "")) or str(data.get("description", "")) or description
             if not description: description = f"Event: {event_type}"
        else:
             description = f"Event: {event_type}"

        # Severity mapping
        if "error" in event_type or "failed" in str(description).lower():
            severity = "Error"
        elif "start" in event_type:
            severity = "Info"
        elif "end" in event_type or "success" in str(description).lower():
            severity = "Success"
        else:
            severity = "Info"
        
        # If user_id is missing, default to System
        # Initiator currently defaults to user_id. We keep it as is, but also provide 'user_id' field.
        user_id_val = log.user_id or "System"
        initiator = user_id_val

        logs.append(AuditLog(
            time=log.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            session_id=log.session_id, # Use real session_id column
            trace_id=log.trace_id,     # Expose trace_id
            user_id=user_id_val,
            type=event_type,
            severity=severity,
            description=description,
            initiator=initiator,
            agent=agent_name,
            node=node_name,
            details=data
        ))
    
    return logs
