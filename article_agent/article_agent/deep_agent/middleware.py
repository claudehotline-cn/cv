import logging
import json
import re
import os
from typing import Any, Dict, Optional

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState
from langchain_core.messages import AIMessage, ToolMessage, BaseMessage
from langgraph.runtime import Runtime

_LOGGER = logging.getLogger(__name__)

class ThinkingLoggerMiddleware(AgentMiddleware):
    """自定义 middleware 用于记录 Main Agent 的思维链内容。"""
    
    async def awrap_model_call(self, request, handler):
        """异步包装模型调用，记录思维内容和工具调用诊断。"""
        # 执行原始模型调用
        response = await handler(request)
        
        # 提取并记录思维内容
        try:
            # ModelResponse.result 是 list[BaseMessage]
            # 直接从消息中提取 reasoning_content
            messages = getattr(response, 'result', None)
            if not messages:
                _LOGGER.warning("[LLM_RESPONSE] No messages in response!")
                return response
            
            for msg in messages:
                # 诊断日志：检查 tool_calls 是否存在
                tool_calls = getattr(msg, 'tool_calls', None)
                content = getattr(msg, 'content', '')
                content_preview = content[:200] if content else "(empty)"
                
                if tool_calls:
                    _LOGGER.info(
                        "[LLM_RESPONSE] tool_calls PRESENT, count=%d, names=%s",
                        len(tool_calls),
                        [tc.get('name', 'unknown') if isinstance(tc, dict) else getattr(tc, 'name', 'unknown') for tc in tool_calls]
                    )
                else:
                    _LOGGER.warning(
                        "[LLM_RESPONSE] tool_calls MISSING! content_preview: %s",
                        content_preview
                    )
                
                # 记录思维链内容
                additional_kwargs = getattr(msg, 'additional_kwargs', {})
                thinking_content = additional_kwargs.get('reasoning_content', '')
                if thinking_content:
                    thinking_preview = thinking_content[:2000]
                    if len(thinking_content) > 2000:
                        thinking_preview += "..."
                    _LOGGER.info(
                        "[CHAIN_OF_THOUGHT] main_agent thinking_len=%d:\n"
                        "--- THINKING START ---\n%s\n--- THINKING END ---",
                        len(thinking_content), thinking_preview
                    )
        except Exception as e:
            _LOGGER.debug("ThinkingLoggerMiddleware.awrap_model_call error: %s", e)
        
        return response
    
    def wrap_tool_call(self, request, handler):
        """同步包装工具调用，记录 tool 调用参数。"""
        try:
            tool_call = getattr(request, 'tool_call', {})
            tool_name = tool_call.get('name', 'unknown') if isinstance(tool_call, dict) else getattr(tool_call, 'name', 'unknown')
            tool_args = tool_call.get('args', {}) if isinstance(tool_call, dict) else getattr(tool_call, 'args', {})
            # 截断长参数以避免日志爆炸
            args_preview = str(tool_args)[:1000]
            if len(str(tool_args)) > 1000:
                args_preview += "..."
            _LOGGER.info(
                "[TOOL_CALL] Main Agent calling tool: %s\nArgs: %s",
                tool_name, args_preview
            )
        except Exception as e:
            _LOGGER.debug("ThinkingLoggerMiddleware.wrap_tool_call logging error: %s", e)
        return handler(request)

    
    async def awrap_tool_call(self, request, handler):
        """异步包装工具调用，记录 tool 调用参数。"""
        try:
            tool_call = getattr(request, 'tool_call', {})
            tool_name = tool_call.get('name', 'unknown') if isinstance(tool_call, dict) else getattr(tool_call, 'name', 'unknown')
            tool_args = tool_call.get('args', {}) if isinstance(tool_call, dict) else getattr(tool_call, 'args', {})
            # 截断长参数以避免日志爆炸
            args_preview = str(tool_args)[:1000]
            if len(str(tool_args)) > 1000:
                args_preview += "..."
            _LOGGER.info(
                "[TOOL_CALL] Main Agent calling tool: %s\nArgs: %s",
                tool_name, args_preview
            )
        except Exception as e:
            _LOGGER.debug("ThinkingLoggerMiddleware.awrap_tool_call logging error: %s", e)
        return await handler(request)


class AssemblerStateMiddleware(AgentMiddleware):
    """Middleware for Assembler SubAgent: 将 Assembler 的输出写入 Store，供 Main Agent Middleware 读取。
    
    这个 Middleware 应该注册在 Assembler SubAgent 上，而不是 Main Agent 上。
    它会在 Assembler 执行完成后，将 md_path 和 article_id 写入跨线程共享的 Store。
    """
    
    def after_agent(self, state: AgentState, runtime: Runtime[Any], result: Any = None) -> Dict[str, Any] | None:
        """After Assembler execution, extract md_path and write to Store for cross-thread access."""
        
        _LOGGER.info("AssemblerStateMiddleware: Extracting assembler output...")
        
        # 尝试从 ToolMessage 或 structured_response 中提取数据
        md_path = None
        article_id = None
        title = None
        article_content = None
        
        # 1. 优先从 ToolMessage 提取（Tool 返回的真实路径，最可靠）
        messages = state.get("messages", [])
        for msg in reversed(messages):
            content_str = str(getattr(msg, "content", ""))
            # 检查是否包含 assemble_article_tool 的输出（包含 md_path 和 article_content）
            if "md_path" in content_str and "article_content" in content_str:
                try:
                    data = json.loads(content_str)
                    if isinstance(data, dict) and data.get("md_path"):
                        md_path = data.get("md_path")
                        article_id = data.get("article_id")
                        title = data.get("title")
                        article_content = data.get("article_content")
                        _LOGGER.info(f"AssemblerStateMiddleware: Found real path in ToolMessage: {md_path}")
                        break
                except:
                    pass
        
        # 2. 回退：从 structured_response 提取（可能是幻觉路径，不太可靠）
        if not md_path:
            if "structured_response" in state and state["structured_response"]:
                resp = state["structured_response"]
                if hasattr(resp, "md_path"):
                    md_path = resp.md_path
                    article_id = getattr(resp, "article_id", None)
                    title = getattr(resp, "title", None)
                    _LOGGER.warning(f"AssemblerStateMiddleware: Using structured_response path (may be hallucinated): {md_path}")
                elif isinstance(resp, dict):
                    md_path = resp.get("md_path")
                    article_id = resp.get("article_id")
                    title = resp.get("title")
                    _LOGGER.warning(f"AssemblerStateMiddleware: Using structured_response path (may be hallucinated): {md_path}")
        
        if md_path:
            _LOGGER.info(f"AssemblerStateMiddleware: Found md_path={md_path}. Updating State.")
            # 直接写入 State，回退 Store 写入（因为 runtime.backend 可能不可用）
            return {
                "_assembler_meta": {
                    "md_path": md_path,
                    "article_id": article_id,
                    "title": title,
                    "article_content": article_content # 尝试传递 content
                }
            }
        else:
            _LOGGER.warning("AssemblerStateMiddleware: Could not extract md_path from Assembler output")
        
        return None


class ArticleContentMiddleware(AgentMiddleware):
    """Middleware to bubbling up article_content from Assembler to Main Agent output (In-Memory)."""
    
    def after_agent(self, state: AgentState, runtime: Runtime[Any], result: Any = None) -> Dict[str, Any] | None:
        """After agent execution, populate article_content from message history."""
        
        # Check if we have a structured response (ArticleAgentOutput)
        if "structured_response" in state and state["structured_response"]:
            resp = state["structured_response"]
            
            # Check current content
            current_content = None
            if hasattr(resp, "article_content"):
                current_content = getattr(resp, "article_content", None)
            elif isinstance(resp, dict):
                current_content = resp.get("article_content")
            
            # Debug log for frontend response
            try:
                if hasattr(resp, "model_dump"):
                    debug_dict = resp.model_dump()
                elif hasattr(resp, "dict"):
                    debug_dict = resp.dict()
                else: 
                    debug_dict = resp if isinstance(resp, dict) else str(resp)
                
                # Truncate long content for log readability but show length
                log_copy = debug_dict.copy() if isinstance(debug_dict, dict) else {}
                content_len = len(log_copy.get("article_content") or "")
                log_copy["article_content"] = f"<CONTENT_LENGTH_{content_len}>"
                _LOGGER.info(f"Middleware: Final structured_response passed to frontend: {json.dumps(log_copy, default=str)}")
            except Exception as e:
                _LOGGER.error(f"Middleware: Failed to log response: {e}")

            # Only proceed if content is missing
            if not current_content or len(current_content) < 100:
                _LOGGER.info("Middleware: article_content missing in final response. Checking sources...")
                
                # ========== 优先层级 0: 从 State 获取 _assembler_meta (最快，最可靠) ==========
                assembler_meta = state.get("_assembler_meta")
                if assembler_meta:
                    meta_md_path = assembler_meta.get("md_path")
                    meta_content = assembler_meta.get("article_content")
                    _LOGGER.info(f"Middleware: Found _assembler_meta in State! md_path={meta_md_path}, content_len={len(meta_content) if meta_content else 0}")
                    
                    if meta_content and len(meta_content) > 100:
                        if hasattr(resp, "model_copy"):
                            new_resp = resp.model_copy(update={
                                "article_content": meta_content,
                                "md_path": meta_md_path
                            })
                            return {"structured_response": new_resp}
                        elif isinstance(resp, dict):
                            resp["article_content"] = meta_content
                            resp["md_path"] = meta_md_path
                            return {"structured_response": resp}
                    
                    # 尝试从文件读取 (如果 State 中只有路径)
                    if meta_md_path and os.path.exists(meta_md_path):
                        try:
                            with open(meta_md_path, 'r', encoding='utf-8') as f:
                                real_content = f.read()
                            _LOGGER.info(f"Middleware: Loaded content from file (State path)! Length: {len(real_content)}")
                            if hasattr(resp, "model_copy"):
                                new_resp = resp.model_copy(update={
                                    "article_content": real_content,
                                    "md_path": meta_md_path
                                })
                                return {"structured_response": new_resp}
                            elif isinstance(resp, dict):
                                resp["article_content"] = real_content
                                resp["md_path"] = meta_md_path
                                return {"structured_response": resp}
                        except Exception as e:
                            _LOGGER.warning(f"Middleware: Failed to read file from State path: {e}")

                # ========== 优先层级 0.5: 从 Store 读取 /_shared/assembler_meta.json (跨线程共享) ==========
                try:
                    # 注意：runtime.backend 可能不可用，加 try-catch
                    if hasattr(runtime, "backend"):
                         shared_data_str = runtime.backend.read("/_shared/assembler_meta.json")
                         if shared_data_str:
                             shared_data = json.loads(shared_data_str)
                             store_md_path = shared_data.get("md_path")
                             store_content = shared_data.get("article_content")
                             _LOGGER.info(f"Middleware: Found data in Store! md_path={store_md_path}, content_len={len(store_content) if store_content else 0}")
                             
                             # 优先使用 Store 中的 article_content
                             if store_content and len(store_content) > 100:
                                 _LOGGER.info(f"Middleware: Successfully loaded content from Store! Length: {len(store_content)}")
                                 if hasattr(resp, "model_copy"):
                                     new_resp = resp.model_copy(update={
                                         "article_content": store_content,
                                         "md_path": store_md_path
                                     })
                                     return {"structured_response": new_resp}
                                 elif isinstance(resp, dict):
                                     resp["article_content"] = store_content
                                     resp["md_path"] = store_md_path
                                     return {"structured_response": resp}
                             
                             # 如果 Store 中没有 content，尝试从文件读取
                             elif store_md_path and os.path.exists(store_md_path):
                                 with open(store_md_path, 'r', encoding='utf-8') as f:
                                     real_content = f.read()
                                 _LOGGER.info(f"Middleware: Loaded content from file (Store path)! Length: {len(real_content)}")
                                 if hasattr(resp, "model_copy"):
                                     new_resp = resp.model_copy(update={
                                         "article_content": real_content,
                                         "md_path": store_md_path
                                     })
                                     return {"structured_response": new_resp}
                                 elif isinstance(resp, dict):
                                     resp["article_content"] = real_content
                                     resp["md_path"] = store_md_path
                                     return {"structured_response": resp}
                except Exception as e:
                    _LOGGER.info(f"Middleware: Store read failed or empty: {e}")
                # ============================================================================

                
                # ========== 优先层级 1: 从消息历史扫描 assemble_article_tool 的返回值 ==========
                _LOGGER.info("Middleware: Trying ToolMessage scanning as fallback...")
                messages = state.get("messages", [])
                for msg in reversed(messages):
                    content_str = str(getattr(msg, "content", ""))
                    # 检查是否是 assemble_article_tool 的输出（包含 md_path 和 article_content）
                    if "md_path" in content_str and "article_content" in content_str:
                        try:
                            data = json.loads(content_str)
                            if isinstance(data, dict):
                                tool_md_path = data.get("md_path")
                                tool_content = data.get("article_content")
                                if tool_md_path and tool_content and len(tool_content) > 100:
                                    _LOGGER.info(f"Middleware: Found assemble_article_tool output! md_path={tool_md_path}, content_len={len(tool_content)}")
                                    
                                    # 直接用 Tool 返回的内容覆盖
                                    if hasattr(resp, "model_copy"):
                                        new_resp = resp.model_copy(update={
                                            "article_content": tool_content,
                                            "md_path": tool_md_path
                                        })
                                        return {"structured_response": new_resp}
                                    elif isinstance(resp, dict):
                                        resp["article_content"] = tool_content
                                        resp["md_path"] = tool_md_path
                                        return {"structured_response": resp}
                        except:
                            pass
                # ============================================================================
                
                _LOGGER.info("Middleware: assemble_article_tool output not found. Falling back to other sources...")
                
                messages = state.get("messages", [])
                found_content = None
                
                # Debug: log message types
                _LOGGER.info(f"Middleware: Scanning {len(messages)} messages.")
                
                for i, msg in enumerate(reversed(messages)):
                    content_str = str(msg.content)
                    msg_type = type(msg).__name__
                    
                    # Log first 200 chars to identify content format
                    if "article_content" in content_str:
                        _LOGGER.info(f"Msg[-{i+1}] ({msg_type}) contains 'article_content'. Preview: {content_str[:200]}...")
                    
                    # 1. 尝试直接从 ToolMessage 中提取 (DeepAgents 可能会把 SubAgent 结果作为 Tool Message)
                    if isinstance(msg, ToolMessage) or (msg_type == "ToolMessage"):
                        # 检查是否是 assemble_article_tool 的输出 (name 属性可能存在于 msg 对象或 additional_kwargs)
                        tool_name = getattr(msg, 'name', '') or msg.additional_kwargs.get('name', '')
                        
                        # 优先匹配 assembler 的工具调用
                        if tool_name == 'assemble_article_tool' or 'assemble' in tool_name or "article_content" in content_str:
                             extracted = self._extract_content(content_str)
                             if extracted:
                                 found_content = extracted
                                 # 如果同时发现了 md_path，也可以顺便更新（修复路径幻觉）
                                 try:
                                     data = json.loads(content_str)
                                     if isinstance(data, dict):
                                         found_path = data.get("md_path")
                                         if found_path:
                                             _LOGGER.info(f"Middleware: Found verifiable md_path in ToolMessage: {found_path}. Overwriting response.")
                                             # Update both content and path
                                             if hasattr(resp, "model_copy"):
                                                 resp = resp.model_copy(update={"article_content": found_content, "md_path": found_path})
                                                 return {"structured_response": resp}
                                             elif isinstance(resp, dict):
                                                 resp["article_content"] = found_content
                                                 resp["md_path"] = found_path
                                                 return {"structured_response": resp}
                                 except Exception as e: 
                                     _LOGGER.warning(f"Middleware: Failed to parse md_path from ToolMessage: {e}")
                                     
                                 _LOGGER.info(f"Middleware: Found content in ToolMessage[-{i+1}] (Name: {tool_name})")
                                 # Update content only if path extraction failed
                                 if hasattr(resp, "model_copy"):
                                     new_resp = resp.model_copy(update={"article_content": found_content})
                                     return {"structured_response": new_resp}
                                 elif isinstance(resp, dict):
                                     resp["article_content"] = found_content
                                     return {"structured_response": resp}
                                 break

                    # 2. 尝试从 AIMessage 中提取 (SubAgent 的输出可能被包装在 AIMessage 中)
                    if isinstance(msg, AIMessage) or (msg_type == "AIMessage"):
                        if "article_content" in content_str:
                             extracted = self._extract_content(content_str)
                             if extracted:
                                 found_content = extracted
                                 _LOGGER.info(f"Middleware: Found content in AIMessage[-{i+1}]")
                                 break
                
                if found_content:
                    _LOGGER.info(f"Middleware: Successfully extracted content ({len(found_content)} chars). Updating response.")
                    # Update response
                    if hasattr(resp, "model_copy"):
                        new_resp = resp.model_copy(update={"article_content": found_content})
                        return {"structured_response": new_resp}
                    elif isinstance(resp, dict):
                        resp["article_content"] = found_content
                        return {"structured_response": resp}
                else:
                    _LOGGER.warning("Middleware: Failed to find article_content in ANY message history.")
                    
                    # 3. Fallback: Try reading from md_path if available in response
                    md_path = None
                    if hasattr(resp, "md_path") and resp.md_path:
                        md_path = resp.md_path
                    elif isinstance(resp, dict) and resp.get("md_path"):
                        md_path = resp.get("md_path")
                        
                    if md_path and os.path.exists(md_path):
                        try:
                            _LOGGER.info(f"Middleware: Reading content from file system: {md_path}")
                            with open(md_path, 'r', encoding='utf-8') as f:
                                file_content = f.read()
                            
                            if len(file_content) > 100:
                                # Update response
                                if hasattr(resp, "model_copy"):
                                    new_resp = resp.model_copy(update={"article_content": file_content})
                                    return {"structured_response": new_resp}
                                elif isinstance(resp, dict):
                                    resp["article_content"] = file_content
                                    return {"structured_response": resp}
                        except Exception as e:
                            _LOGGER.error(f"Middleware: Failed to read from md_path: {e}")
        
        # Fallback: If structured_response is missing but we have a final message with content
        elif result and hasattr(result, "content") and len(str(result.content)) > 100:
             _LOGGER.warning("Middleware: Structured response MISSING. Fallback: Wrapping raw message content.")
             # Construct a fallback dictionary matching ArticleAgentOutput
             fallback_resp = {
                 "status": "success",
                 "title": "Generated Article",
                 "md_path": "",
                 "md_url": "",
                 "summary": "Generated from raw output.",
                 "word_count": len(str(result.content)),
                 "article_content": str(result.content),
                 "error_message": None
             }
             _LOGGER.info(f"Middleware: Created fallback structured_response with {len(str(result.content))} chars.")
             return {"structured_response": fallback_resp}

        return None

        return None

    def _extract_content(self, text: str) -> Optional[str]:
        """Helper to extract article_content from a string (JSON or partial JSON)."""
        if not text: return None
        
        # 1. Try strict JSON
        try:
            data = json.loads(text)
            if isinstance(data, dict) and data.get("article_content"):
                return data["article_content"]
        except:
            pass
            
        # 2. Try ast.literal_eval (Handles Python dict string representation: {'key': 'value'})
        try:
            import ast
            # Only attempt if it looks like a dict
            if text.strip().startswith("{") and "article_content" in text:
                data = ast.literal_eval(text)
                if isinstance(data, dict) and data.get("article_content"):
                    return data["article_content"]
        except:
            pass
            
        # 3. Try clean prefix JSON (e.g. DATA_RESULT:...)
        if "DATA_RESULT:" in text:
            try:
                clean = text.split("DATA_RESULT:", 1)[1].strip()
                data = json.loads(clean)
                if isinstance(data, dict) and data.get("article_content"):
                    return data["article_content"]
            except:
                pass

        # 4. Try Regex for key='value' or key="value" format (Common in some LLM text outputs)
        # Matches: article_content='...' or article_content="..."
        # Note: This is a basic regex and might fail on complex nested quotes, but handles simple cases.
        try:
            # Match article_content='...' single usage
            patterns = [
                r"article_content='((?:[^'\\]|\\.)*)'",  # Single qoutes
                r'article_content="((?:[^"\\]|\\.)*)"',  # Double quotes
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.DOTALL)
                if match:
                    return match.group(1)
        except Exception as e:
            _LOGGER.debug(f"Middleware: Regex extraction failed: {e}")

        # 5. Try "Header: Content" format (Common in Assembler natural language output)
        # Matches text after "- 文章内容:" or "文章内容:"
        markers = ["- 文章内容:", "文章内容:"]
        for marker in markers:
            if marker in text:
                try:
                    # Extract everything after marker
                    parts = text.split(marker, 1)
                    if len(parts) > 1:
                        candidate = parts[1].strip()
                        # Clean up known trailing phrases from prompt
                        if "任务圆满结束" in candidate:
                            candidate = candidate.split("任务圆满结束")[0].strip()
                        if len(candidate) > 100: # Simple validation to ensure it's actual content
                             return candidate
                except:
                    pass

        return None

class IllustratorValidationMiddleware(AgentMiddleware):
    """验证 Illustrator 生成的图片路径是否存在，并尝试修复。"""
    
    def after_agent(self, state: AgentState, runtime: Runtime[Any], result: Any = None) -> Dict[str, Any] | None:
        """检查 Illustrator 输出的 markdown 文件中的图片路径。"""
        
        # 1. 尝试从结构化输出中获取 output
        output = None
        if "structured_response" in state and state["structured_response"]:
            output = state["structured_response"]
        # 2. 或者尝试从最后的消息中解析 (如果 Illustrator 还没有完全结构化)
        elif result and hasattr(result, "content"):
             # 这里简化处理，暂时只处理结构化输出或明确的 dict
             pass
             
        md_path = None
        if isinstance(output, dict):
            md_path = output.get("final_markdown_path")
        elif hasattr(output, "final_markdown_path"):
            md_path = output.final_markdown_path
            
        if not md_path:
            return None

        # 验证文件是否存在
        if not md_path or not os.path.exists(md_path):
            _LOGGER.warning(f"IllustratorValidationMiddleware: Markdown file not found at {md_path}")
            return None
            
        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 提取所有图片链接
            # 匹配 ![alt](url)
            img_refs = re.findall(r'!\[.*?\]\((.*?)\)', content)
            
            valid_count = 0
            missing_paths = []
            
            for img_path in img_refs:
                # 忽略网络 URL
                if img_path.startswith("http://") or img_path.startswith("https://"):
                    valid_count += 1
                    continue
                    
                if os.path.exists(img_path):
                    valid_count += 1
                else:
                    missing_paths.append(img_path)
            
            _LOGGER.info(f"Illustrator Output Validation: {valid_count} verified, {len(missing_paths)} missing images in {md_path}")
            
            if missing_paths:
                _LOGGER.warning(f"Missing images in draft: {missing_paths}")
                
        except Exception as e:
             _LOGGER.error(f"IllustratorValidationMiddleware error: {e}")
             
        return None
