
import asyncio
import os
import sys

# Ensure article_agent is in python path
sys.path.append(os.getcwd())

from article_agent.deep_agent.graph import get_article_deep_agent_graph
from langchain_core.messages import HumanMessage

async def run_test():
    print("Starting test run...")
    app = get_article_deep_agent_graph()
    
    # Use HumanMessage to ensure the agent "hears" the instruction
    inputs = {
        "messages": [HumanMessage(content="请基于以下素材介绍Transformer架构：https://github.com/huggingface/transformers/blob/main/README.md (article_id=test-fix-009)，目标字数1000字")]
    }
    
    config = {"configurable": {"thread_id": "test-thread-003"}}
    
    async for event in app.astream(inputs, config=config):
        for key, value in event.items():
            print(f"\n[Event] {key}")
            # print(value)

if __name__ == "__main__":
    asyncio.run(run_test())
