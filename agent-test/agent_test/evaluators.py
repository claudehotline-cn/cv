from typing import List, Any, Optional
from langchain_core.messages import BaseMessage
from agentevals.trajectory.match import create_trajectory_match_evaluator
from agentevals.trajectory.llm import create_trajectory_llm_as_judge, TRAJECTORY_ACCURACY_PROMPT

def get_trajectory_match_evaluator(mode: str = "strict"):
    """
    Get a trajectory match evaluator.
    modes: strict, unordered, subset, superset
    """
    return create_trajectory_match_evaluator(trajectory_match_mode=mode)

def get_llm_judge_evaluator(model: str = "openai:gpt-4o", prompt=TRAJECTORY_ACCURACY_PROMPT):
    """
    Get an LLM-as-a-Judge evaluator for trajectory accuracy.
    """
    return create_trajectory_llm_as_judge(model=model, prompt=prompt)
