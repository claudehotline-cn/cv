from typing import Any, Dict, List, Optional
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
    自定义 Human-in-the-Loop 中间件，在特定 SubAgent 调用之前触发中断。
    
    由于所有 SubAgent 都通过 'task' 工具调用，标准 HumanInTheLoopMiddleware
    无法按 subagent_type 参数过滤。此中间件解决这个问题。
    
    配置:
        interrupt_subagents: 需要中断的 subagent 名称列表
        allowed_decisions: 允许的决策类型
    """
    
    def __init__(
        self, 
        interrupt_subagents: List[str] = None,
        allowed_decisions: List[str] = None,
        description: str = "请确认是否继续"
    ):
        super().__init__()
        # 修改：在 visualizer_agent 和 report_agent 完成后中断
        self.interrupt_subagents = interrupt_subagents or ["visualizer_agent", "report_agent"]
        self.allowed_decisions = allowed_decisions or ["approve", "reject"]
        self.description = description
    
    async def awrap_tool_call(self, request, handler):
        """在工具调用之后检查是否需要中断（针对 visualizer_agent）。"""
        tool_call = getattr(request, 'tool_call', {})
        if isinstance(tool_call, dict):
            tool_name = tool_call.get('name', '')
            args = tool_call.get('args', {})
        else:
            tool_name = getattr(tool_call, 'name', '')
            args = getattr(tool_call, 'args', {})
        
        # DEBUG: Log every tool call to see what's coming through
        _LOGGER.info(f"[HITL DEBUG] awrap_tool_call invoked: tool_name='{tool_name}', args_keys={list(args.keys()) if isinstance(args, dict) else type(args)}")
        
        # 只处理 task 工具
        if tool_name == 'task':
            subagent_type = args.get('subagent_type', '')
            _LOGGER.info(f"[HITL DEBUG] task tool detected: subagent_type='{subagent_type}', interrupt_subagents={self.interrupt_subagents}")
            
            # 检查是否是需要中断的 subagent
            if subagent_type in self.interrupt_subagents:
                _LOGGER.info(f"[HITL] Executing {subagent_type} first, will interrupt after completion")
                
                # 先执行 subagent，让它完成生成（图表/报告）
                response = await handler(request)
                
                _LOGGER.info(f"[HITL] {subagent_type} completed, triggering interrupt for user review")
                
                # 构造中断请求（artifact 数据已通过 subgraph streaming 发送给前端）
                interrupt_value = {
                    "action_requests": [{
                        "name": subagent_type,
                        "args": args,
                        "description": f"{self.description}\n\n{subagent_type} 已完成，请审核结果。"
                    }],
                    "review_configs": [{
                        "action_name": subagent_type,
                        "allowed_decisions": self.allowed_decisions
                    }]
                }
                
                # 触发中断，等待用户决策
                interrupt_res = interrupt(interrupt_value)
                
                # 如果代码继续执行到这里，说明用户已恢复
                _LOGGER.info(f"[HITL] Resumed with: {interrupt_res}")
                
                # 检查用户的决定
                if isinstance(interrupt_res, dict) and "decisions" in interrupt_res:
                    decisions = interrupt_res["decisions"]
                    if decisions and isinstance(decisions, list):
                        decision = decisions[0]
                        if decision.get("type") == "reject":
                            feedback = decision.get("message", f"用户拒绝了{subagent_type}输出")
                            _LOGGER.info(f"[HITL] User rejected {subagent_type}: {feedback}")
                            
                            # 返回用户反馈作为工具执行结果
                            if subagent_type == "visualizer_agent":
                                return f"USER_INTERRUPT: 用户对图表不满意。反馈: {feedback}。请根据反馈修改图表，然后再次调用 visualizer_agent。"
                            elif subagent_type == "report_agent":
                                return f"USER_INTERRUPT: 用户对分析报告不满意。反馈: {feedback}。请根据反馈修改报告，然后再次调用 report_agent。"
                            else:
                                return f"USER_INTERRUPT: 用户对 {subagent_type} 输出不满意。反馈: {feedback}。请根据反馈重新执行该任务。"

                # 用户批准，返回明确的批准消息，告知 Main Agent 继续下一步
                _LOGGER.info(f"[HITL] User approved, returning approval message")
                if subagent_type == "visualizer_agent":
                    return f"USER_APPROVED: 用户已批准图表。图表生成完成，请继续执行下一步任务（如生成分析报告）。不要再次调用 visualizer_agent。"
                elif subagent_type == "report_agent":
                    return f"USER_APPROVED: 用户已批准分析报告。报告已完成，任务结束。不要再次调用 report_agent。"
                else:
                    return f"USER_APPROVED: 用户已批准 {subagent_type} 的输出。请继续执行下一步，不要重复调用同一个 subagent。"
        
        # 继续执行工具调用
        return await handler(request)

