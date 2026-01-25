"""Python Sub-Agent Module"""
from __future__ import annotations

import logging
import operator
import re
import json
from typing import TypedDict, Annotated, Sequence, Any, Literal

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command
from deepagents import CompiledSubAgent

from agent_core.runtime import build_chat_llm
from ..tools import (
    df_profile_tool, python_execute_tool
)
from ..prompts import (
    PYTHON_AGENT_DESCRIPTION, PYTHON_AGENT_PROMPT
)
from ..skills.registry import SKILLS_REGISTRY

from agent_core.settings import get_settings
from agent_core.events import RedisEventBus, AuditEmitter
from agent_core.decorators import node_wrapper

_settings = get_settings()
_redis_bus = RedisEventBus(_settings.redis_url)
_audit_emitter = AuditEmitter(_redis_bus.redis)


_LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# Python Agent Definition
# -------------------------------------------------------------------------

class PythonAgentState(TypedDict):
    """Python Agent 的状态"""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    task_description: str
    analysis_id: str
    df_profile_result: str  # Step 1 的结果
    python_code: str        # LLM 生成的代码
    python_result: str      # Step 2 的结果
    retry_count: int        # 重试次数
    error_feedback: str     # 错误反馈

@node_wrapper("df_profile", emitter=_audit_emitter, graph_id="python_agent")
def step1_df_profile(state: PythonAgentState, config: RunnableConfig) -> dict:
    """Step 1: 调用 df_profile 查看数据结构"""
    _LOGGER.info("[Python Agent Fixed Flow] Step 1: df_profile")
    
    # Check for user_id and analysis_id from config
    configurable = config.get("configurable", {})
    user_id = configurable.get("user_id", "NOT_FOUND")
    analysis_id = configurable.get("analysis_id", "")
    
    task_description = ""
    messages = state.get("messages", [])
    if messages:
         # 最后一条消息作为任务描述
         task_description = str(messages[-1].content)
    

    
    try:
        result = df_profile_tool.invoke({"df_name": "sql_result", "analysis_id": analysis_id})
        _LOGGER.info("[Python Agent] df_profile result: %s", result[:500] if len(result) > 500 else result)
        return {"df_profile_result": result, "analysis_id": analysis_id, "task_description": task_description}
    except Exception as e:
        _LOGGER.error("[Python Agent] df_profile failed: %s", e)
        return {"df_profile_result": f"Error: {e}", "analysis_id": analysis_id, "task_description": task_description}

@node_wrapper("llm_generate", emitter=_audit_emitter, graph_id="python_agent")
def step2_llm_generate_code(state: PythonAgentState, config: RunnableConfig) -> dict:
    """Step 2: LLM 根据 df_profile 结果生成 Python 代码"""
    _LOGGER.info("[Python Agent Fixed Flow] Step 2: LLM generate code")
    task = state.get("task_description", "")
    df_info = state.get("df_profile_result", "")
    
    # 1. 提取 Skill (从 task_description 中解析 [skill=xxx])
    skill_match = re.search(r'\[skill[=:]?\s*([a-zA-Z0-9_]+)\]', task, re.IGNORECASE)
    skill_name = skill_match.group(1).lower() if skill_match else "general"
    
    # 2. 获取 Skill 配置
    skill_config = SKILLS_REGISTRY.get(skill_name, SKILLS_REGISTRY["general"])
    skill_display_name = skill_config.get("name", "General")
    skill_instruction = skill_config.get("instruction", "")
    skill_examples = skill_config.get("examples", "")
    
    _LOGGER.info("[Python Agent] Active Skill: %s (%s)", skill_name, skill_display_name)
    
    # 3. 动态构建 Prompt
    prompt = PYTHON_AGENT_PROMPT.format(
        skill_name=skill_display_name,
        skill_instruction=skill_instruction,
        skill_examples=skill_examples
    )
    
    # 4. 拼接具体任务和数据信息
    final_prompt = f"""{prompt}

【任务描述】
{task}

【数据结构】（来自 df_profile）
{df_info}
"""
    # --- 重试逻辑：如果有错误反馈，添加到 Prompt ---
    error_feedback = state.get("error_feedback", "")
    if error_feedback:
        _LOGGER.warning("[Python Agent] Retrying with error feedback: %s", error_feedback[:200])
        final_prompt += f"""
python
【上一次生成的代码执行错误】
错误信息: {error_feedback}

请修正上述代码，确保不再发生此错误。
"""
    # ---------------------------------------------
    
    # 获取 LLM
    llm = build_chat_llm(task_name="python_agent")
    
    # Use Standard Content Block
    from ..utils.message_utils import extract_text_from_message
    
    messages = [HumanMessage(content=[
        {"type": "text", "text": final_prompt}
    ])]
    
    # 🚀 使用流式输出 + with_config 设置 tags，让 metadata 包含 agent 名称
    full_response = None
    for chunk in llm.with_config({"tags": ["agent:python_agent"]}).stream(messages):
        if full_response is None:
            full_response = chunk
        else:
            full_response += chunk
    response = full_response
    
    code = extract_text_from_message(response)
    # 提取代码块
    if "```python" in code:
        code = code.split("```python")[1].split("```")[0]
    elif "```" in code:
        code = code.split("```")[1].split("```")[0]
    
    _LOGGER.info("[Python Agent] LLM generated code: %s", code[:300])
    return {"python_code": code.strip()}

@node_wrapper("python_execute", emitter=_audit_emitter, graph_id="python_agent")
def step3_python_execute(state: PythonAgentState, config: RunnableConfig) -> Command[Literal["llm_generate", "format_output"]]:
    """步骤 3: 执行 LLM 生成的 Python 代码，使用 Command 决定下一步走向"""
    _LOGGER.info("[Python Agent Fixed Flow] Step 3: python_execute")
    code = state.get("python_code", "")
    # 直接从 config 读取 analysis_id，不依赖 state 传递
    analysis_id = config.get("configurable", {}).get("analysis_id", "")
    
    retry_count = state.get("retry_count", 0)
    
    if not code:
        return Command(
            update={"python_result": "Error: No code to execute", "retry_count": 0},
            goto="format_output"
        )
    
    try:
        # Pass config to tool invocation so it gets user_id
        result = python_execute_tool.invoke({"code": code, "analysis_id": analysis_id}, config=config)
        _LOGGER.info("[Python Agent] python_execute result: %s", result[:500] if len(result) > 500 else result)
        
        # 检查执行结果是否包含错误
        import json
        is_success = True
        error_msg = ""
        try:
            res_json = json.loads(result) if isinstance(result, str) else result
            if isinstance(res_json, dict) and not res_json.get("success", False):
                is_success = False
                error_msg = res_json.get("error", "Unknown error")
        except:
            pass
        
        if not is_success:
            _LOGGER.warning("[Python Agent] Execution failed: %s", error_msg)
            if retry_count < 3:
                _LOGGER.info("[Python Agent] Retrying... Attempt %d", retry_count + 1)
                return Command(
                    update={"python_result": result, "retry_count": retry_count + 1, "error_feedback": error_msg},
                    goto="llm_generate"
                )
            else:
                return Command(
                    update={"python_result": result, "error_feedback": error_msg},
                    goto="format_output"
                )
        
        # 成功清除错误状态
        return Command(
            update={"python_result": result, "error_feedback": ""},
            goto="format_output"
        )
        
    except Exception as e:
        _LOGGER.error("[Python Agent] python_execute failed: %s", e)
        if retry_count < 3:
            return Command(
                update={"python_result": f"Error: {e}", "retry_count": retry_count + 1, "error_feedback": str(e)},
                goto="llm_generate"
            )
        else:
            return Command(
                update={"python_result": f"Error: {e}", "error_feedback": str(e)},
                goto="format_output"
            )

@node_wrapper("format_output", emitter=_audit_emitter, graph_id="python_agent")
def format_final_output(state: PythonAgentState, config: RunnableConfig) -> dict:
    """格式化最终输出为 Agent 消息"""
    result = state.get("python_result", "")
    _LOGGER.info("[Python Agent] format_final_output result length: %d", len(result))
    return {"messages": [AIMessage(content=f"PYTHON_AGENT_COMPLETE: {result}")]}

# check_python_retry 函数已移除，改用 Command 模式在 python_execute 中直接决定走向

# 构建 Python Agent Graph
python_agent_graph = StateGraph(PythonAgentState)
python_agent_graph.add_node("df_profile", step1_df_profile)
python_agent_graph.add_node("llm_generate", step2_llm_generate_code)
python_agent_graph.add_node("python_execute", step3_python_execute)
python_agent_graph.add_node("format_output", format_final_output)

python_agent_graph.add_edge(START, "df_profile")
python_agent_graph.add_edge("df_profile", "llm_generate")
python_agent_graph.add_edge("llm_generate", "python_execute")

# Command 模式：python_execute 内部直接决定下一步，无需 conditional_edges
python_agent_graph.add_edge("format_output", END)

python_agent_runnable = python_agent_graph.compile()

python_agent = CompiledSubAgent(
    name="python_agent",
    description=PYTHON_AGENT_DESCRIPTION,
    runnable=python_agent_runnable,
)
