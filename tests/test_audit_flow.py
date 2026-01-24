
import requests
import time
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_audit")

BASE_URL = "http://localhost:18111"

def test_sql_agent_audit():
    # 1. Create Session (default agent = data_agent)
    logger.info("Creating session...")
    resp = requests.post(f"{BASE_URL}/sessions/")
    assert resp.status_code == 200, f"Failed to create session: {resp.text}"
    session_data = resp.json()
    session_id = session_data["id"]
    logger.info(f"Session Created: {session_id}")
    
    # 2. Send Message that triggers SQL Agent (db_list_tables)
    # "List all tables" maps to tool db_list_tables_tool
    logger.info("Sending chat message: 'List all tables in database'")
    resp = requests.post(
        f"{BASE_URL}/sessions/{session_id}/chat",
        json={"message": "List all tables in database"}
    )
    assert resp.status_code == 200, f"Chat failed: {resp.text}"
    
    # Consume Stream
    logger.info("Consuming stream event...")
    for line in resp.iter_lines():
        if line:
            # logger.info(f"Stream: {line.decode('utf-8')}")
            pass
            
    # Allow some time for async audit processing (Redis -> Worker -> DB)
    logger.info("Waiting for audit logs...")
    time.sleep(3)
    
    # 3. Check Audit Logs
    resp = requests.get(f"{BASE_URL}/audit/?limit=20")
    assert resp.status_code == 200, f"Audit list failed: {resp.text}"
    logs = resp.json()
    
    found_sql_tool = False
    
    logger.info("--- Audit Logs ---")
    for log in logs:
        # Check for tool execution
        # Type: tool_start or tool_end
        # Description: Executing: db_list_tables (or cleaned name)
        # Agent: Should be "Data Agent" (if my propagate works)
        # Node: Should be "SQL Agent" (if my propagate works)
        
        logger.info(f"[{log['time']}] Type={log['type']} Agent={log['agent']} Node={log['node']} Desc={log['description']}")
        
        if log['type'] == 'tool_start' or log['type'] == 'tool_end':
            # Check description for the tool name
            # db_list_tables_tool might be formatted as "Db List Tables Tool" or similar
            if "db_list_tables" in log['description'].lower() or "db list tables" in log['description'].lower():
                found_sql_tool = True
                
                # VERIFY IDENTITY
                # My fix added tags=["agent:sql_agent"]
                # My audit.py parser extracts "Data Agent" if "data" and "agent" in tags.
                # It also extracts "SQL Agent" as node if "subagent" logic works, OR if "sql_agent" is in tags.
                
                # Note: node name logic in audit.py:
                # if tool=="task" -> uses AOP subagent name
                # if tool!="task" -> uses format_node_name(tool) e.g. "Db List Tables"
                
                # So if I see Node="Db List Tables", that's good.
                # Crucially, I want to see if "Agent" column is populated correctly.
                
                if log['agent'] == "Data Agent":
                    logger.info("✅ SUCCESS: Agent identity correctly propagated!")
                else:
                    logger.warning(f"⚠️ Agent identity missing or wrong: {log['agent']}")
                    
    if found_sql_tool:
        logger.info("✅ SUCCESS: Found SQL Tool execution in logs.")
    else:
        logger.error("❌ FAILURE: Did not find SQL Tool execution in logs.")

if __name__ == "__main__":
    try:
        test_sql_agent_audit()
    except Exception as e:
        logger.error(f"Test Exception: {e}")
