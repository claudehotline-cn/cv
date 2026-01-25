from typing import Any, Dict, List, Optional, Union
import json
import logging
import os
import uuid
import re
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, HumanMessage, ToolMessage, trim_messages
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from langgraph.types import interrupt
from deepagents.backends import StoreBackend

from .events import AuditEmitter


_LOGGER = logging.getLogger(__name__)


class SensitiveToolMiddleware(AgentMiddleware):
    """
    Generalized HITL Middleware that interrupts execution when a sensitive tool is called.
    """
    
    def __init__(
        self, 
        emitter: AuditEmitter = None,
        sensitive_tools: List[str] = None,
        allowed_decisions: List[str] = None,
        description: Union[str, Dict[str, str]] = "High risk operation detected, please confirm."
    ):
        super().__init__()
        self.emitter = emitter
        self.sensitive_tools = sensitive_tools or []
        self.allowed_decisions = allowed_decisions or ["approve", "reject"]
        self.description = description
    
    async def awrap_tool_call(self, request, handler):
        # Extract tool name and args
        tool_call = getattr(request, 'tool_call', {})
        if isinstance(tool_call, dict):
            tool_name = tool_call.get('name', '')
            tool_args = tool_call.get('args', {})
            tool_call_id = tool_call.get('id', '')
        else:
            tool_name = getattr(tool_call, 'name', '')
            tool_args = getattr(tool_call, 'args', {})
            tool_call_id = getattr(tool_call, 'id', '')
        
        # Check if tool is sensitive
        # Also supports the legacy "task" tool based subagent interruption pattern if configured
        is_sensitive = tool_name in self.sensitive_tools
        
        # Legacy support: if "task" tool and args['subagent_type'] is in sensitive_tools (as a convention)
        if not is_sensitive and tool_name == 'task':
            subagent = tool_args.get('subagent_type', '')
            if subagent in self.sensitive_tools:
                is_sensitive = True
        
        if is_sensitive:
            _LOGGER.info(f"[HITL] Intercepting sensitive tool: {tool_name}")
            
            # Determine description
            if isinstance(self.description, dict):
                desc = self.description.get(tool_name, self.description.get("default", "Sensitive Action Detected"))
            else:
                desc = self.description

            # Emit hitl_requested
            current_run_id = None
            if hasattr(request, "runtime") and request.runtime:
                 # 1. Try config
                 config = getattr(request.runtime, "config", None)
                 if config:
                     current_run_id = config.get("metadata", {}).get("run_id")
                 
                 # 2. Try context (if config failed)
                 if not current_run_id:
                     ctx = getattr(request.runtime, "context", {})
                     # Context might be dict or object
                     if isinstance(ctx, dict):
                         current_run_id = ctx.get("run_id") or ctx.get("configurable", {}).get("run_id")
            
            # Extract session/thread info
            session_id = None
            thread_id = None
            if hasattr(request, "runtime"):
                cfg = getattr(request.runtime, "config", {})
                meta = cfg.get("metadata", {})
                configurable = cfg.get("configurable", {})
                
                session_id = meta.get("session_id") or configurable.get("session_id")
                thread_id = meta.get("thread_id") or configurable.get("thread_id")
                
                if not session_id and isinstance(getattr(request.runtime, "context", {}), dict):
                     ctx = request.runtime.context
                     session_id = ctx.get("session_id") or ctx.get("configurable", {}).get("session_id")

            if self.emitter and current_run_id:
                await self.emitter.emit(
                    event_type="hitl_requested",
                    run_id=str(current_run_id),
                    session_id=str(session_id) if session_id else None,
                    thread_id=str(thread_id) if thread_id else None,
                    span_id=None, 
                    component="middleware",
                    payload={
                        "tool_name": tool_name,
                        "tool_args": str(tool_args)[:2000], 
                        "description": desc
                    }
                )

            # Prepare Interrupt Payload
            interrupt_value = {
                "action_requests": [{
                    "name": tool_name,
                    "args": tool_args,
                    "description": desc
                }],
                "review_configs": [{
                    "action_name": tool_name,
                    "allowed_decisions": self.allowed_decisions
                }]
            }
            
            # Trigger LangGraph Interrupt
            # This yields control back to the Runtime/User
            interrupt_res = interrupt(interrupt_value)
            
            _LOGGER.info(f"[HITL] Resumed with decision: {interrupt_res}")
            
            # Handle Resume
            # interrupt() returns the value passed to resume()
            decisions = None
            if isinstance(interrupt_res, list):
                decisions = interrupt_res
            elif isinstance(interrupt_res, dict) and "decisions" in interrupt_res:
                decisions = interrupt_res["decisions"]
            
            if decisions and isinstance(decisions, list) and len(decisions) > 0:
                decision = decisions[0]
                decision_type = decision.get("type")
                message = decision.get("message", "")
                
                if self.emitter and current_run_id:
                    await self.emitter.emit(
                        event_type="hitl_approved" if decision_type == "approve" else "hitl_rejected",
                        run_id=str(current_run_id),
                        component="middleware",
                        payload={
                            "tool_name": tool_name,
                            "decision": decision_type,
                            "reason": message
                        }
                    )

                if decision_type == "reject":
                    content = f"USER_INTERRUPT: Operation '{tool_name}' rejected by user. Feedback: {message}. Stop or modify your plan."
                    _LOGGER.info(f"[HITL] Rejected: {content}")
                    return ToolMessage(content=content, tool_call_id=tool_call_id, status="error")
                
                if decision_type == "approve":
                    _LOGGER.info(f"[HITL] Approved: Proceeding with {tool_name}")
                    # Validation: check if args were modified?
                    # For now, we proceed with original request or could allow args override if supported locally
                    # If we wanted arg modification, decision payload would need "new_args"
                    return await handler(request)

            # Default if structure unclear but resumed: Assume Approval if not rejected
            return await handler(request)
        
        return await handler(request)


class FileAttachmentMiddleware(AgentMiddleware):
    """
    Generic middleware to extract file attachments from user messages and save to workspace.
    
    Supports: PDF, Excel (xlsx/xls), CSV, images (png/jpg/gif/webp), and other common file types.
    
    When users upload files via frontend, they come as ContentBlocks with:
    - type: "file"
    - mimeType: "application/pdf" | "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" | ...
    - data: base64-encoded content
    - metadata.filename: original filename
    """
    
    # Supported MIME types and their extensions
    SUPPORTED_TYPES = {
        # Documents
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.ms-excel": ".xls",
        "text/csv": ".csv",
        # Images
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        # Text
        "text/plain": ".txt",
        "text/markdown": ".md",
    }
    
    def __init__(self, upload_dir: str = "/data/workspace/uploads"):
        super().__init__()
        self.upload_dir = upload_dir
    
    def before_agent(self, state: Dict[str, Any], runtime: Runtime[Any]) -> Optional[Dict[str, Any]]:
        """Process input messages to extract file attachments."""
        import base64
        
        messages = state.get("messages", [])
        if not messages:
            return None
        
        # Find the last human message
        last_human_idx = None
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if isinstance(msg, HumanMessage) or (hasattr(msg, 'type') and msg.type == 'human'):
                last_human_idx = i
                break
        
        if last_human_idx is None:
            return None
        
        last_msg = messages[last_human_idx]
        content = getattr(last_msg, 'content', None)
        
        # Check if content is a list (multimodal message)
        if not isinstance(content, list):
            return None
        
        file_paths = []
        text_parts = []
        
        for block in content:
            if not isinstance(block, dict):
                continue
            
            block_type = block.get('type', '')
            mime_type = block.get('mimeType', '')
            
            # Extract text parts
            if block_type == 'text':
                text_parts.append(block.get('text', ''))
            
            # Extract file attachments
            elif block_type == 'file' and mime_type in self.SUPPORTED_TYPES:
                file_data = block.get('data', '')
                filename = block.get('metadata', {}).get('filename', f'uploaded{self.SUPPORTED_TYPES[mime_type]}')
                
                if file_data:
                    try:
                        # Decode and save file
                        file_bytes = base64.b64decode(file_data)
                        os.makedirs(self.upload_dir, exist_ok=True)
                        
                        # Sanitize filename
                        safe_filename = re.sub(r'[^\w\-_\.]', '_', filename)
                        file_path = os.path.join(self.upload_dir, f"{uuid.uuid4().hex[:8]}_{safe_filename}")
                        
                        with open(file_path, 'wb') as f:
                            f.write(file_bytes)
                        
                        file_paths.append(file_path)
                        _LOGGER.info(f"[FileAttachmentMiddleware] Saved file to {file_path}")
                    except Exception as e:
                        _LOGGER.error(f"[FileAttachmentMiddleware] Failed to save file: {e}")
        
        # If we found files, update the message
        if file_paths:
            original_text = '\n'.join(text_parts)
            file_info = "\n\n[系统提示] 用户上传了以下文件，请使用相应工具处理：\n"
            file_info += "\n".join([f"- {path}" for path in file_paths])
            
            new_text = original_text + file_info
            new_msg = HumanMessage(content=new_text)
            
            new_messages = list(messages)
            new_messages[last_human_idx] = new_msg
            
            _LOGGER.info(f"[FileAttachmentMiddleware] Processed {len(file_paths)} file attachments")
            return {"messages": new_messages}
        
        return None


class PolicyMiddleware(AgentMiddleware):
    """
    RBAC Middleware to enforce tool execution permissions based on user roles.
    
    Loads policy from `policy.yaml` (default) or config.
    """
    
    def __init__(self, policy_path: str = "policy.yaml"):
        super().__init__()
        self.policy_path = policy_path
        self._policy_cache = None
        self._load_policy()
        
    def _load_policy(self):
        import yaml
        if os.path.exists(self.policy_path):
            try:
                with open(self.policy_path, "r") as f:
                    self._policy_cache = yaml.safe_load(f)
                _LOGGER.info(f"[PolicyMiddleware] Loaded policy from {self.policy_path}")
            except Exception as e:
                _LOGGER.error(f"[PolicyMiddleware] Failed to load policy: {e}")
                self._policy_cache = {}
        else:
            _LOGGER.warning(f"[PolicyMiddleware] Policy file not found at {self.policy_path}, defaulting to deny-all for unknown roles.")
            self._policy_cache = {}

    def _check_permission(self, role: str, tool_name: str) -> bool:
        if not self._policy_cache:
            return False # Fail safe
            
        roles_config = self._policy_cache.get("roles", {})
        role_config = roles_config.get(role)
        
        if not role_config:
            return False
            
        allowed = role_config.get("allow", [])
        denied = role_config.get("deny", [])
        
        # 1. Check Deny (Explicit deny wins)
        if "*" in denied or tool_name in denied:
            return False
            
        # 2. Check Allow
        if "*" in allowed or tool_name in allowed:
            return True
            
        return False
        
    async def awrap_tool_call(self, request, handler):
        """
        Intercept tool calls and check permissions.
        """
        tool_call = getattr(request, 'tool_call', {})
        if isinstance(tool_call, dict):
            tool_name = tool_call.get('name', '')
            # args = tool_call.get('args', {})
        else:
            tool_name = getattr(tool_call, 'name', '')
            # args = getattr(tool_call, 'args', {})
            
        if not tool_name:
            return await handler(request)
            
        # Extract user role. 
        user_role = os.environ.get("AGENT_USER_ROLE", "guest")
        
        if not self._check_permission(user_role, tool_name):
            error_msg = f"PERMISSION DENIED: User role '{user_role}' is not allowed to use tool '{tool_name}'."
            _LOGGER.warning(f"[PolicyMiddleware] {error_msg}")
            
            # Return a ToolMessage indicating failure, preventing execution
            tool_call_id = tool_call.get('id', '') if isinstance(tool_call, dict) else getattr(tool_call, 'id', '')
            return ToolMessage(content=error_msg, tool_call_id=tool_call_id, status="error")
            
        _LOGGER.info(f"[PolicyMiddleware] ALLOWED: {tool_name} for role {user_role}")
        return await handler(request)

