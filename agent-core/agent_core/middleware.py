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
from deepagents.backends import StoreBackend


_LOGGER = logging.getLogger(__name__)


class SubAgentHITLMiddleware(AgentMiddleware):
    """
    Custom HITL Middleware for SubAgent Interruption.
    """
    
    def __init__(
        self, 
        interrupt_subagents: List[str] = None,
        allowed_decisions: List[str] = None,
        description: Union[str, Dict[str, str]] = "Please confirm to proceed"
    ):
        super().__init__()
        self.interrupt_subagents = interrupt_subagents or ["visualizer_agent", "report_agent"]
        self.allowed_decisions = allowed_decisions or ["approve", "reject"]
        self.description = description
    
    async def awrap_tool_call(self, request, handler):
        tool_call = getattr(request, 'tool_call', {})
        if isinstance(tool_call, dict):
            tool_name = tool_call.get('name', '')
            args = tool_call.get('args', {})
        else:
            tool_name = getattr(tool_call, 'name', '')
            args = getattr(tool_call, 'args', {})
        
        _LOGGER.info(f"[HITL DEBUG] awrap_tool_call: {tool_name}")
        
        if tool_name == 'task':
            subagent_type = args.get('subagent_type', '')
            
            if subagent_type in self.interrupt_subagents:
                _LOGGER.info(f"[HITL] Executing {subagent_type} first, will interrupt after completion")
                
                response = await handler(request)
                
                # Extract content for preview
                preview_content = None
                if isinstance(response, str):
                    preview_content = response
                elif hasattr(response, 'update') and isinstance(response.update, dict):
                    # Handle Command object
                    msgs = response.update.get("messages", [])
                    if msgs:
                        last_msg = msgs[-1]
                        if isinstance(last_msg, ToolMessage):
                            preview_content = last_msg.content
                        elif hasattr(last_msg, 'content'):
                            preview_content = last_msg.content
                
                # Determine description based on subagent_type
                if isinstance(self.description, dict):
                    desc = self.description.get(subagent_type, self.description.get("default", "操作完成，请确认是否继续"))
                else:
                    desc = self.description

                interrupt_value = {
                    "action_requests": [{
                        "name": subagent_type,
                        "args": args,
                        "description": desc
                    }],
                    "review_configs": [{
                        "action_name": subagent_type,
                        "allowed_decisions": self.allowed_decisions
                    }],
                    "preview": preview_content
                }
                
                interrupt_res = interrupt(interrupt_value)
                
                # Get tool_call_id for ToolMessage
                tool_call_id = tool_call.get('id', '') if isinstance(tool_call, dict) else getattr(tool_call, 'id', '')
                
                _LOGGER.info(f"[HITL] interrupt_res type: {type(interrupt_res)}, value: {interrupt_res}")
                
                # interrupt() returns the exact value passed to Command(resume=...)
                # Backend passes: [{"type": "approve"|"reject", "message": "..."}]
                decisions = None
                if isinstance(interrupt_res, list):
                    decisions = interrupt_res
                elif isinstance(interrupt_res, dict) and "decisions" in interrupt_res:
                    decisions = interrupt_res["decisions"]
                
                if decisions and isinstance(decisions, list) and len(decisions) > 0:
                    decision = decisions[0]
                    if decision.get("type") == "reject":
                        feedback = decision.get("message", "")
                        content = f"USER_INTERRUPT: 用户拒绝了 {subagent_type} 的输出。反馈: {feedback}。请根据反馈重新调用 {subagent_type}。"
                        _LOGGER.info(f"[HITL] User rejected, returning: {content}")
                        return ToolMessage(content=content, tool_call_id=tool_call_id)

                # Generic approval message with subagent_type
                content = f"USER_APPROVED: {subagent_type} approved."
                _LOGGER.info(f"[HITL] User approved or no decision, returning: {content}")
                
                return ToolMessage(content=content, tool_call_id=tool_call_id)
        
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

