#!/usr/bin/env python3
"""End-to-End Test for Article Agent after ContextVar refactoring"""

import asyncio
import logging
import uuid

logging.basicConfig(level=logging.INFO, format='%(name)s - %(message)s')
logger = logging.getLogger("e2e_test")

async def test_article_agent():
    """Test the full Article Agent with a real URL"""
    from langchain_core.messages import HumanMessage
    from article_agent.graph import get_article_deep_agent_graph
    from agent_core.store import get_async_checkpointer
    
    # Initialize checkpointer first (required for graph)
    await get_async_checkpointer()
    
    logger.info("=" * 60)
    logger.info("Article Agent E2E Test - Post ContextVar Refactor")
    logger.info("=" * 60)
    
    # Create the graph
    graph = get_article_deep_agent_graph()
    logger.info("✅ Graph created successfully!")
    
    # Test config with explicit task_id
    thread_id = str(uuid.uuid4())  # Full UUID required by PostgreSQL checkpointer
    config = {
        "configurable": {
            "thread_id": thread_id,
            "session_id": "e2e_test",
            "task_id": "test_run_001",  # Explicit task_id for testing
        }
    }
    
    # Test prompt - using a simple Wikipedia article
    test_url = "https://en.wikipedia.org/wiki/Python_(programming_language)"
    test_prompt = f"""请根据以下网页内容，撰写一篇关于 Python 编程语言的简介文章：

参考网址：{test_url}

要求：
1. 简要介绍 Python 的历史
2. 说明 Python 的主要特点
3. 列举 Python 的应用领域

目标字数：约 1000 字"""
    
    logger.info(f"Thread ID: {thread_id}")
    logger.info(f"Task ID: test_run_001")
    logger.info(f"Test URL: {test_url}")
    logger.info("-" * 60)
    
    # Send message and stream response
    input_message = HumanMessage(content=test_prompt)
    
    try:
        step_count = 0
        async for event in graph.astream(
            {"messages": [input_message]},
            config=config,
            stream_mode="values"
        ):
            step_count += 1
            if "messages" in event and event["messages"]:
                last_msg = event["messages"][-1]
                msg_type = type(last_msg).__name__
                content_preview = str(last_msg.content)[:200] if hasattr(last_msg, 'content') else "N/A"
                logger.info(f"[Step {step_count}] {msg_type}: {content_preview}...")
            
            # Limit steps to avoid infinite loops in test
            if step_count >= 10:
                logger.info("⚠️ Reached step limit (10), stopping test")
                break
                
        logger.info("=" * 60)
        logger.info(f"✅ Test completed! Total steps: {step_count}")
        logger.info("=" * 60)
        return True
        
    except Exception as e:
        logger.error(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_article_agent())
    exit(0 if result else 1)
