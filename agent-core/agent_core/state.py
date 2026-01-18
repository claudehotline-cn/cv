from typing import TypedDict, Annotated, List, Union, Dict, Any
from langchain_core.messages import BaseMessage
import operator

class BaseAgentState(TypedDict):
    """Base generic state for all agents."""
    messages: Annotated[List[BaseMessage], operator.add]
    # Optional generic fields that might be useful across agents
    user_id: str
    session_id: str
    metadata: Dict[str, Any]
