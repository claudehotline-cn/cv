
import sys
import os

# Add project root to sys.path
sys.path.append(os.path.abspath("/home/chaisen/projects/cv/agent-langchain"))

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_refactor")

def test_extract_text_utility():
    from agent_langchain.utils.message_utils import extract_text_from_message
    from langchain_core.messages import AIMessage
    
    logger.info("Testing extract_text_from_message...")
    
    # Case 1: String
    assert extract_text_from_message("hello") == "hello"
    
    # Case 2: Content Block List
    blocks = [
        {"type": "text", "text": "foo"},
        {"type": "image", "url": "http://..."},
        {"type": "text", "text": "bar"}
    ]
    assert extract_text_from_message(blocks) == "foo\nbar"
    
    # Case 3: Message Object with String
    msg_str = AIMessage(content="world")
    assert extract_text_from_message(msg_str) == "world"
    
    # Case 4: Message Object with Blocks
    msg_blocks = AIMessage(content=blocks)
    assert extract_text_from_message(msg_blocks) == "foo\nbar"
    
    logger.info("✅ extract_text_from_message passed all tests.")

def verify_imports():
    logger.info("Verifying agent imports...")
    try:
        from agent_langchain.deep_agent.subagents.sql import sql_agent
        from agent_langchain.deep_agent.subagents.python import python_agent
        from agent_langchain.deep_agent.subagents.visualizer import visualizer_agent
        from agent_langchain.deep_agent.subagents.report import report_agent
        logger.info("✅ All agents imported successfully.")
    except Exception as e:
        logger.error(f"❌ Import failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_extract_text_utility()
    verify_imports()
