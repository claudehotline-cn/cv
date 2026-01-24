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

        # Check top-level metadata/tags first (from my core fix)
        # Note: 'data' is the payload. My core fix puts tags/metadata in 'data'.
        tags = data.get("tags") or []
        metadata = data.get("metadata") or {}
        
        # Try to detect Agent name from metadata
        if metadata.get("agent_name"):
            agent_name = metadata.get("agent_name")
        
        # Sub-agent name from metadata (populated by sub-agents)
        if metadata.get("sub_agent"):
            node_name = metadata.get("sub_agent")
        
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
            node_name = model
            description = f"Querying {model}"
            
        elif event_type == "llm_end":
            inner_payload = parse_inner(data.get("data"))
            tokens = 0
            usage = inner_payload.get("usage") or {}
            if isinstance(usage, dict):
                tokens = usage.get("total_tokens", 0)
            description = f"LLM generation complete ({tokens} tokens)"

        elif event_type == "chain_start":
            inner_payload = parse_inner(data.get("data"))
            chain = get_name(inner_payload, "chain", "Chain")
            node_name = chain
            description = f"Started {chain}"
            
        elif event_type == "chain_end":
            description = "Chain execution finished"
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
            session_id=log.trace_id, # trace_id is used as session_id context
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
