
import asyncio
import logging
from langchain_core.runnables import RunnableConfig
from data_agent.subagents.sql import sql_step1_list_tables, SQLAgentState

# 配置 logging
logging.basicConfig(level=logging.INFO)

from agent_core.audit import AuditCallbackHandler
from agent_core.events import RedisEventBus
from langchain_core.callbacks import BaseCallbackHandler

async def main():
    print("Starts Debug SQL Agent...")
    state: SQLAgentState = {"messages": []}
    
    # Initialize EventBus and Audit Handler
    # Use internal redis hostname from docker-compose
    bus = RedisEventBus(redis_url="redis://langgraph-redis:6379")
    audit_handler = AuditCallbackHandler(event_bus=bus)
    
    # Mock Config
    config: RunnableConfig = {
        "configurable": {
            "user_id": "debug_user_001",
            "session_id": "debug_session_123",
            "analysis_id": "debug_analysis_001"
        },
        "metadata": {
            "session_id": "debug_session_123"
        },
        "callbacks": [audit_handler]
    }
    
    # Mock runtime/store (not used in step 1 logic really, pass None/dummy)
    class MockRuntime:
        state = "running"
    
    print("Invoking sql_step1_list_tables...")
    try:
        # Note: step signature: (state, config, store, runtime)
        res = sql_step1_list_tables(state, config, None, MockRuntime())
        print("Result:", res)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    asyncio.run(main())
