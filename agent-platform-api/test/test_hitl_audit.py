
import requests
import json
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_hitl")

BASE_URL = "http://localhost:18111"

def test_hitl_flow():
    # 1. Create Session
    logger.info("Creating session...")
    resp = requests.post(f"{BASE_URL}/sessions/")
    assert resp.status_code == 200, f"Failed to create session: {resp.text}"
    session_id = resp.json()["id"]
    logger.info(f"Session Created: {session_id}")

    # 2. Send Prompt (Trigger Visualizer -> HITL)
    prompt = "按城市统计每月订单总金额，绘制一个折线图"
    logger.info(f"Sending prompt: '{prompt}'")
    
    chat_url = f"{BASE_URL}/sessions/{session_id}/chat"
    
    interrupted = False
    
    # 3. Consume Chat Stream (Expecting Interrupt)
    with requests.post(chat_url, json={"message": prompt}, stream=True) as r:
        for line in r.iter_lines():
            if line:
                decoded = line.decode('utf-8')
                if decoded.startswith("data: "):
                    data_str = decoded[6:]
                    try:
                        data = json.loads(data_str)
                        if data.get("type") == "interrupt":
                            logger.info(f"🚨 RECEIVED INTERRUPT: {data}")
                            interrupted = True
                            break # Stop consuming, we need to resume
                        elif data.get("type") == "error":
                             logger.error(f"Stream Error: {data}")
                    except:
                        pass
    
    if not interrupted:
        logger.warning("Did not receive explicit interrupt event. Checking approvals via API...")
        # Check if approval exists?
        # Maybe the stream finished but state is interrupted.
        pass

    # 4. Resume
    logger.info("Resuming with 'approve'...")
    resume_url = f"{BASE_URL}/sessions/{session_id}/resume"
    resume_payload = {"decision": "approve", "feedback": "Looks good"}
    
    with requests.post(resume_url, json=resume_payload, stream=True) as r:
         assert r.status_code == 200, f"Resume failed: {r.text}"
         for line in r.iter_lines():
             if line:
                 # logger.info(f"Resume Stream: {line.decode('utf-8')}")
                 pass
                 
    logger.info("Resume stream finished.")
    
    # 5. Verify Audit Logs
    time.sleep(5)  # Allow async processing
    
    # 5a. Check Run Summary via API (to see if orphans exist internally)
    # We need the Run ID. Let's find it via list.
    logger.info("Fetching Run ID...")
    runs = requests.get(f"{BASE_URL}/audit/runs?limit=1").json()
    items = runs.get("items", [])
    if not items:
        logger.error("No runs found!")
        return
        
    latest_run_id = items[0]["run_id"]
    logger.info(f"Latest Run ID: {latest_run_id}")
    
    # 5b. Fetch Trace
    trace = requests.get(f"{BASE_URL}/audit/runs/{latest_run_id}/summary").json()
    spans = trace.get("spans", [])
    
    logger.info(f"Total Spans in Trace: {len(spans)}")
    
    # Check for Orphans (parent_id missing but not root)
    orphans = []
    interrupt_events = 0
    
    # Count interrupts in spans
    interrupted_spans = [s for s in spans if s['status'] == 'interrupted']
    logger.info(f"Interrupted Spans Found: {len(interrupted_spans)}")
    
    for s in spans:
        sid = s['span_id']
        pid = s['parent_span_id']
        
        # Root span has no parent, but should match run_id (or be the root agent)
        if not pid:
             if sid == latest_run_id:
                 logger.info(f"Root Span Confirmed: {sid}")
             else:
                 logger.error(f"Orphan Span Found: {sid} ({s['name']})")
                 orphans.append(sid)
                 
    if not orphans:
        logger.info("✅ SUCCESS: No orphans found in HITL trace.")
    else:
        logger.error(f"❌ FAILURE: {len(orphans)} orphans found.")

if __name__ == "__main__":
    test_hitl_flow()
