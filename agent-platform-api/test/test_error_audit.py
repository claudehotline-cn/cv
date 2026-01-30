
import requests
import json
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_error")

BASE_URL = "http://localhost:18111"

def test_error_audit():
    # 1. Create Session
    logger.info("Creating session...")
    resp = requests.post(f"{BASE_URL}/sessions/")
    assert resp.status_code == 200, f"Failed to create session: {resp.text}"
    session_id = resp.json()["id"]
    logger.info(f"Session Created: {session_id}")

    # 2. Send BAD SQL Prompt
    # This should trigger sql_agent -> run_sql with invalid query
    prompt = "Execute this SQL: SELECT * FROM non_existent_table_xyz_123"
    logger.info(f"Sending error-inducing prompt: '{prompt}'")
    
    chat_url = f"{BASE_URL}/sessions/{session_id}/chat"
    
    # Consume Stream
    with requests.post(chat_url, json={"message": prompt}, stream=True) as r:
        for line in r.iter_lines():
             pass # just consume
             
    # 3. Verify Audit Logs
    time.sleep(5)  # Allow async processing
    
    # Fetch latest run
    runs = requests.get(f"{BASE_URL}/audit/runs?limit=1").json()
    items = runs.get("items", [])
    if not items:
        logger.error("No runs found!")
        return
        
    latest_run_id = items[0]["run_id"]
    logger.info(f"Checking Run ID: {latest_run_id}")
    
    # Fetch Trace
    trace = requests.get(f"{BASE_URL}/audit/runs/{latest_run_id}/summary").json()
    spans = trace.get("spans", [])
    failures = trace.get("failures", [])
    
    logger.info(f"Total Spans: {len(spans)}")
    logger.info(f"Total Failures in Summary: {len(failures)}")
    
    # Check for Error Events in Spans
    error_spans = [s for s in spans if s['status'] == 'failed' or s.get('type') == 'tool_failed']
    logger.info(f"Failed Spans: {len(error_spans)}")
    
    for fail in failures:
        logger.info(f"Failure Event: {fail}")
        
    found_sql_error = False
    for s in spans:
        # Check if any span mentions the error
        # We might need to check 'events' child if available, or just status
        pass

if __name__ == "__main__":
    test_error_audit()
