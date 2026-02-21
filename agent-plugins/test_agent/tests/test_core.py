import pytest
from agent_test.mocks import mock_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from test_agent.agent import TestAgent
from test_agent.graph import get_graph

def test_agent_initialization():
    agent = TestAgent()
    assert agent.get_config()["key"] == "test_agent"

def test_agent_graph_compile():
    agent = TestAgent()
    graph = agent.get_graph()
    assert graph is not None

def test_agent_execution_mocked():
    # Example using mock_chat_model
    # We call get_graph directly to inject checkpointer for testing state
    
    # Run with in-memory checkpointer
    checkpointer = InMemorySaver()
    compiled_graph = get_graph(checkpointer=checkpointer)
    
    result = compiled_graph.invoke(
        {"messages": [("user", "Hello")]},
        config={"configurable": {"thread_id": "test-1"}}
    )
    assert result is not None
