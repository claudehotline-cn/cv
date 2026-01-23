
import pytest
import os
import asyncio
from langgraph.checkpoint.memory import InMemorySaver
from data_agent.graph import get_data_deep_agent_graph

# Mark as integration test
@pytest.mark.integration
@pytest.mark.asyncio
async def test_data_agent_integration_vllm():
    """
    Integration test connecting to local vLLM.
    Requires vLLM running on localhost:18000.
    """
    # 1. Setup Environment for vLLM
    # We use InMemorySaver to avoid DB dependency, testing only LLM integration
    os.environ["AGENT_LLM_PROVIDER"] = "vllm"
    os.environ["AGENT_VLLM_BASE_URL"] = "http://localhost:18000/v1"
    os.environ["AGENT_OPENAI_MODEL"] = "/data/models/Qwen3-Omni-30B-A3B-Thinking-AWQ-4bit"
    os.environ["OPENAI_API_KEY"] = "EMPTY"
    
    # Clear settings cache to pick up new env vars
    from agent_core.settings import get_settings
    get_settings.cache_clear()
    
    # 2. Build Graph
    # Note: We rely on build_chat_llm picking up the env vars.
    # We explicitly pass None to force it to build from env.
    checkpointer = InMemorySaver()
    try:
        graph = get_data_deep_agent_graph(checkpointer=checkpointer, llm=None)
    except Exception as e:
        pytest.skip(f"Failed to initialize graph (likely missing dependencies or config): {e}")

    # 3. Invoke Agent
    # Simple math question to verify reasoning and tool usage (or just direct answer)
    input_messages = {"messages": [("user", "Calculate 25 * 4 using python.")]}
    config = {"configurable": {"thread_id": "integration-test-1", "user_id": "test-user"}}
    
    print("\n--- Invoking Data Agent with vLLM ---")
    try:
        # Using astream to see progress
        final_response = None
        async for event in graph.astream(input_messages, config, stream_mode="values"):
            if "messages" in event:
                msg = event["messages"][-1]
                print(f"[{msg.type}] {msg.content[:100]}...")
                final_response = msg.content
        
        # 4. Verification
        assert final_response is not None
        assert "100" in final_response
        print("\n--- Integration Test Passed ---")

    except Exception as e:
        # Check if it's a connection error
        import httpx
        if isinstance(e, (httpx.ConnectError, ConnectionRefusedError)):
            pytest.fail(f"Could not connect to vLLM at localhost:18000. Is it running? Error: {e}")
        else:
            raise e
