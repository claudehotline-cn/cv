
import requests
import json
import sys

# Agent API port mapped in docker-compose is 18111
BASE_URL = "http://localhost:18111"
RUN_ID = "976648cd-bac4-4580-8bd8-3f9469e5ce4b"  # From recent logs

def check_trace():
    url = f"{BASE_URL}/audit/runs/{RUN_ID}/summary"
    print(f"Fetching {url}...")
    try:
        resp = requests.get(url)
        if resp.status_code != 200:
            print(f"Error: {resp.status_code} {resp.text}")
            return
        
        data = resp.json()
        print(f"Run Status: {data.get('status')}")
        
        # Check Steps/Rows/Trace
        # The API structure usually returns 'steps' or a flat list?
        # Let's inspect keys
        print(f"Keys: {data.keys()}")
        
        # Use 'spans' instead of 'steps'
        steps = data.get("spans", [])
        failures = data.get("failures", [])
        
        print(f"Total Spans: {len(steps)}")
        print(f"Total Failures: {len(failures)}")
        
        if failures:
             print("--- FAILURES FOUND ---")
             for f in failures:
                 print(f"ERROR: {f}")

        # Check for hidden errors in tool outputs
        print("--- TOOL OUTPUTS ---")
        for s in steps:
             if s.get('type') == 'tool':
                 # Find events for this span? usage of summary endpoint implies 'events' might not be nested in 'spans'
                 # But we can check if there's a payload in the span status? No.
                 # Actually the Summary endpoint returns 'recent_events' list separately.
                 pass
                 
        events = data.get("recent_events", [])
        for e in events:
            if e.get("type") == "tool_call_executed":
                payload = e.get("payload", {})
                output = payload.get("output_digest", "")
                print(f"Tool Output: {output[:200]}")
        
        # Build Map
        span_map = {s['span_id']: s for s in steps}
        
        orphans = []
        for s in steps:
            span_id = s.get('span_id')
            parent_id = s.get('parent_span_id')
            
            # Root node usually has parent_id None/Null
            if not parent_id:
                print(f"Root/Top Node found: {span_id} ({s.get('node_name')})")
                continue
                
            if parent_id not in span_map:
                # Is it the Run ID itself?
                if parent_id == RUN_ID:
                     print(f"Linked to Run ID root: {span_id}")
                else:
                     orphans.append(s)
                     print(f"ORPHAN: {span_id} ({s.get('node_name')}) -> Missing Parent {parent_id}")

        if not orphans:
            print("✅ API check passed: No orphans found in JSON response.")
        else:
            print(f"❌ API check failed: {len(orphans)} orphans found.")
            
        # Design Doc Alignment Check
        event_types = {}
        for s in steps:
            etype = s.get("type", "unknown")
            event_types[etype] = event_types.get(etype, 0) + 1
            
        print("--- SPAN TYPES (From Spans) ---")
        for k, v in event_types.items():
            print(f"{k}: {v}")
            
        # Check RAW EVENTS for subagent_started
        raw_types = {}
        events = data.get("recent_events", [])
        for e in events:
             etype = e.get("type", "unknown")
             raw_types[etype] = raw_types.get(etype, 0) + 1
             
        print("--- RAW EVENT TYPES ---")
        for k, v in raw_types.items():
            print(f"{k}: {v}")

        if "subagent_started" in raw_types:
             print("✅ Design Alignment: 'subagent_started' event detected in raw stream.") 
        else:
             print("❌ Design Alignment Failed: 'subagent_started' NOT found in raw stream.")
            
        # Dump json for inspection
        with open("debug_trace.json", "w") as f:
            json.dump(data, f, indent=2)
            
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        RUN_ID = sys.argv[1]
    
    # Try to list runs first to get valid ID
    print("Fetching recent runs...")
    try:
         list_resp = requests.get(f"{BASE_URL}/audit/runs?limit=5")
         if list_resp.status_code == 200:
             resp_json = list_resp.json()
             runs = resp_json.get("items", [])
             if runs:
                  latest = runs[0]
                  # API returns request_id now
                  key = 'request_id' if 'request_id' in latest else 'run_id'
                  print(f"Latest Run: {latest[key]} ({latest.get('status')})")
                  if not RUN_ID or RUN_ID == "latest":
                       RUN_ID = latest[key]
                       print(f"Checking Latest Run: {RUN_ID}")
             else:
                 print("No runs found in listing.")
                 sys.exit(0)
    except Exception as e:
         print(f"Failed to list runs: {e}")
         
    if RUN_ID:
        check_trace()
    else:
        print("No Run ID to check.")
