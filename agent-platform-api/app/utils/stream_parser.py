"""
Qwen Stream Parser - 解析流式输出中的 <think> 标签和工具调用
"""
import re
import json
from typing import List, Dict, Any, Optional
from langchain_core.messages import AIMessageChunk, ToolMessage


class QwenStreamParser:
    """
    解析 Qwen 模型的流式输出，分离思维链 (<think>) 和正常内容。
    
    使用方式:
        parser = QwenStreamParser()
        for chunk in stream:
            events = parser.process(chunk)
            for event in events:
                if event["type"] == "thinking":
                    # 处理思考内容
                elif event["type"] == "content":
                    # 处理普通内容
                elif event["type"] == "tool_call_chunk":
                    # 处理工具调用碎片
                elif event["type"] == "tool_result":
                    # 处理工具执行结果
        
        # 流结束时，刷新剩余内容
        final_events = parser.flush()
    """
    
    def __init__(self):
        # 状态标记
        self.in_think_block = False
        self.buffer = ""  # 用于处理标签截断的缓冲区
        
        # 工具调用聚合器 (用于处理工具参数碎片)
        self.tool_calls_buffer: Dict[int, Dict[str, str]] = {}
    
    def process(self, chunk: Any) -> List[Dict[str, Any]]:
        """
        接收一个 LangGraph chunk，返回解析后的事件字典列表。
        
        Args:
            chunk: LangGraph 的消息块 (AIMessageChunk 或 ToolMessage)
        
        Returns:
            List[Dict]: 事件列表，每个事件包含:
                - type: "thinking" | "content" | "tool_call_chunk" | "tool_result"
                - data: 对应的内容
        """
        events = []
        
        # ---------------------------
        # 1. 处理工具执行结果 (ToolMessage)
        # ---------------------------
        if isinstance(chunk, ToolMessage):
            events.append({
                "type": "tool_result",
                "tool_call_id": chunk.tool_call_id,
                "name": chunk.name,
                "output": chunk.content
            })
            return events
        
        # ---------------------------
        # 2. 处理 AI 的输出 (AIMessageChunk)
        # ---------------------------
        if isinstance(chunk, AIMessageChunk):
            
            # A. 处理工具调用请求 (Tool Calls)
            if hasattr(chunk, 'tool_call_chunks') and chunk.tool_call_chunks:
                for tc in chunk.tool_call_chunks:
                    # 聚合逻辑，处理参数碎片
                    index = tc.get("index", 0)
                    if index not in self.tool_calls_buffer:
                        self.tool_calls_buffer[index] = {"name": "", "args": "", "id": ""}
                    
                    if tc.get("name"):
                        self.tool_calls_buffer[index]["name"] += tc["name"]
                    if tc.get("id"):
                        self.tool_calls_buffer[index]["id"] += tc["id"]
                    if tc.get("args"):
                        self.tool_calls_buffer[index]["args"] += tc["args"]
                    
                    # 发送增量更新事件
                    events.append({
                        "type": "tool_call_chunk",
                        "index": index,
                        "data": tc
                    })
            
            # B. 处理文本内容 (Thinking vs Normal Content)
            content = chunk.content
            if content:
                # 如果 content 是列表 (structured content)，提取文本
                if isinstance(content, list):
                    text_parts = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                        elif isinstance(item, str):
                            text_parts.append(item)
                    content = "".join(text_parts)
                
                if isinstance(content, str) and content:
                    # 调用标签解析逻辑
                    parsed_events = self._parse_tags(content)
                    events.extend(parsed_events)
        
        return events
    
    def _parse_tags(self, new_text: str) -> List[Dict[str, Any]]:
        """
        解析 <think> 标签，处理标签截断的情况。
        
        Args:
            new_text: 新到达的文本片段
        
        Returns:
            List[Dict]: 解析出的事件列表
        """
        self.buffer += new_text
        events = []
        
        while True:
            # 如果不在 think 模式，寻找 <think>
            if not self.in_think_block:
                match = re.search(r"<think>", self.buffer)
                if match:
                    # 1. 标签前的内容是普通回复
                    pre_text = self.buffer[:match.start()]
                    if pre_text:
                        events.append({"type": "content", "data": pre_text})
                    
                    # 2. 切换状态
                    self.in_think_block = True
                    self.buffer = self.buffer[match.end():]  # 切掉 <think>
                    continue  # 继续循环处理剩余 buffer
                else:
                    # 检查是否有截断风险 (例如 buffer 结尾是 "<th")
                    if self._is_truncated_tag(self.buffer):
                        break  # 暂停处理，等待下一个 chunk
                    else:
                        # 安全，全部作为普通内容输出
                        if self.buffer:
                            events.append({"type": "content", "data": self.buffer})
                        self.buffer = ""
                        break
            
            # 如果在 think 模式，寻找 </think>
            else:
                match = re.search(r"</think>", self.buffer)
                if match:
                    # 1. 标签前的内容是思考内容
                    think_text = self.buffer[:match.start()]
                    if think_text:
                        events.append({"type": "thinking", "data": think_text})
                    
                    # 2. 切换状态
                    self.in_think_block = False
                    self.buffer = self.buffer[match.end():]  # 切掉 </think>
                    continue
                else:
                    if self._is_truncated_tag(self.buffer):
                        break
                    else:
                        # 安全，全部作为思考内容输出
                        if self.buffer:
                            events.append({"type": "thinking", "data": self.buffer})
                        self.buffer = ""
                        break
        
        return events
    
    def _is_truncated_tag(self, text: str) -> bool:
        """
        检测字符串末尾是否包含不完整的 XML 标签。
        
        例如: "<", "<t", "<thi", "</", "</thi" 都返回 True
        
        Args:
            text: 要检测的字符串
        
        Returns:
            bool: 是否包含截断的标签
        """
        if not text:
            return False
        # 检查末尾 8 位是否包含 < 但没有 >
        # 8 是因为 "</think>" 有 8 个字符
        tail = text[-8:]
        return bool(re.search(r"<[^>]*$", tail))
    
    def flush(self) -> List[Dict[str, Any]]:
        """
        流结束时调用，强制输出 buffer 中剩余的内容。
        
        Returns:
            List[Dict]: 剩余内容的事件列表
        """
        events = []
        if self.buffer:
            event_type = "thinking" if self.in_think_block else "content"
            events.append({"type": event_type, "data": self.buffer})
            self.buffer = ""
        return events
    
    def get_completed_tool_calls(self) -> List[Dict[str, Any]]:
        """
        获取已完成的工具调用（args 是有效 JSON 的）。
        
        Returns:
            List[Dict]: 完成的工具调用列表
        """
        completed = []
        for index, tc in self.tool_calls_buffer.items():
            try:
                args = json.loads(tc["args"]) if tc["args"] else {}
                completed.append({
                    "index": index,
                    "id": tc["id"],
                    "name": tc["name"],
                    "args": args
                })
            except json.JSONDecodeError:
                # 参数还不完整，跳过
                pass
        return completed
    
    def reset(self):
        """重置解析器状态"""
        self.in_think_block = False
        self.buffer = ""
        self.tool_calls_buffer = {}
