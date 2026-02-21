import pytest
import os
import sys
from unittest.mock import MagicMock
from langgraph.checkpoint.memory import InMemorySaver
from agent_test import mock_chat_model

# 1. Mock Environment (must be before imports that check env)
os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["AGENT_MODEL_NAME"] = "gpt-4-test"
os.environ["LITE_MODEL_NAME"] = "gpt-3.5-test"

# Mock minio dependency before importing article_agent
sys.modules["minio"] = MagicMock()
sys.modules["minio.error"] = MagicMock()

from article_agent.graph import get_article_deep_agent_graph

def test_article_agent_structure():
    """Test that the Article Agent graph assembles correctly."""
    # 1. Mock
    llm = mock_chat_model(["Hello"])
    
    # 2. Compile
    checkpointer = InMemorySaver()
    graph = get_article_deep_agent_graph(model=llm, checkpointer=checkpointer)
    
    # 3. Inspect
    assert graph is not None
    # Check that nodes exist. compiled graph wrapper from deepagents might hide internals,
    # but top level graph should be runnable.
    nodes = graph.get_graph().nodes
    print(f"Graph Nodes: {list(nodes.keys())}")
    assert len(nodes) > 0

@pytest.mark.asyncio
async def test_article_agent_smoke_run():
    """Smoke test: Invoke Article Agent with simple input."""
    # 1. Mock a standard Deep Agent response sequence
    # Main Agent -> Router -> [Action] -> Final Response
    # Since we don't mock sub-agents here yet, we expect it to try to route.
    # We provide a mocked response that skips tool calls to just return final answer,
    # or simulates a simple thought process.
    
    mock_responses = [
        "Thought: Verification mode. I will just answer.\nFinal Answer: Test passed."
    ]
    base_llm = mock_chat_model(mock_responses)
    
    class MockLLMWrapper:
        def __init__(self, llm):
            self.llm = llm
        
        def bind_tools(self, *args, **kwargs):
            return self
        
        def with_structured_output(self, *args, **kwargs):
            return self
            
        def __getattr__(self, name):
            return getattr(self.llm, name)
        
        async def ainvoke(self, *args, **kwargs):
            return await self.llm.ainvoke(*args, **kwargs)

    llm = MockLLMWrapper(base_llm)
    
    checkpointer = InMemorySaver()
    
    graph = get_article_deep_agent_graph(model=llm, checkpointer=checkpointer)
    
    input_data = {"messages": [("user", "Write an article about testing")]}
    config = {"configurable": {"thread_id": "test-article-1"}}
    
    # Run
    # Since deepagents uses a compiled state graph, we invoke it.
    # Note: deepagents usually requires specific config or state schema.
    # We try standard invocation.
    
    events = []
    async for event in graph.astream(input_data, config=config):
        events.append(event)
        # Verify we get some output
    
    assert len(events) > 0
    print("Article Agent smoke test completed.")
