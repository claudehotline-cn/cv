import asyncio
import httpx
import sys
import json

BASE_URL = "http://agent-api:8000"
SESSION_ID = "b4d57dc5-b9f4-49dd-8f71-ef8b9d9f1841"

async def verify_trace():
    async with httpx.AsyncClient(timeout=30.0) as client:
        print(f"--- Checking Trace for Session {SESSION_ID} ---")
        
        # 1. Find Run
        resp = await client.get(f"{BASE_URL}/audit/runs?limit=50")
        runs = resp.json().get("items", [])
        target_run = next((r for r in runs if r["session_id"] == SESSION_ID), None)
        
        if not target_run:
            print("FAILED: No run found for this session.")
            sys.exit(1)
            
        run_id = target_run["run_id"]
        print(f"Run ID: {run_id}")
        print(f"Status: {target_run['status']}")
        
        # 2. Get Spans
        resp = await client.get(f"{BASE_URL}/audit/runs/{run_id}/summary")
        data = resp.json()
        spans = data.get("spans", [])
        
        orphans = []
        params_node = None
        
        print("\n--- Spans Analysis ---")
        for s in spans:
            name = s['name']
            sid = s['span_id']
            pid = s['parent_span_id']
            
            print(f"[{s['status']}] {name} (ID: {sid}, Parent: {pid if pid else 'None'})")
            
            # Check for orphans (excluding Root Agent/Chain which might be top level)
            # Typically logic: if type='tool' or 'node', must have parent.
            # Classification Logic
            # Check if parent exists in the span list
            known_span_ids = {s['span_id'] for s in spans}
            
            if pid:
                if pid not in known_span_ids:
                     # If parent is NOT in the list of spans, it might be the Run ID?
                     if pid == run_id:
                         # Parent is the Run ID. Does a Span exist for the Run ID?
                         # Usually runs don't have a span with same ID unless explicitly created.
                         print(f"  [!] Parent is Run ID but Run-Span not found: {name} (P: {pid})")
                         orphans.append(s)
                     else:
                         print(f"  >>> FAILURE: {name} has Parent {pid} which DOES NOT EXIST")
                         orphans.append(s)
            
            # Classification Logic
            if not pid:
                # partial string match for agent/node which are usually top level roots of the graph execution
                is_root_candidate = "agent" in name.lower() or s['type'] == 'node' or s['type'] == 'chain'
                
                print(f"  [?] Node with No Parent: {name} (Type: {s['type']})")
                # DUMP RAW EVENTS FOR THIS ORPHAN
                print(f"    >>> DUMPING EVENTS FOR ORPHAN SPAN {sid} <<<")
                # Assuming 'data' contains 'recent_events' from the run summary
                start_event = next((e for e in data.get('recent_events', []) if e.get('span_id') == sid and 'start' in e.get('type', '')), None)
                if start_event:
                    print(f"    [Start Event] Type: {start_event['type']}, Component: {start_event.get('component')}")
                    print(f"    [Start Payload]: {json.dumps(start_event.get('payload'), ensure_ascii=False)}")
                else:
                    print("    [!] No Start Event found in recent_events for this span!")
                    # Dump any event for this span
                    related = [e for e in data.get('recent_events', []) if e.get('span_id') == sid]
                    for i, e in enumerate(related):
                        print(f"    [Event {i}] Type: {e['type']} Payload: {json.dumps(e.get('payload'), ensure_ascii=False)}")
                
                if is_root_candidate:
                     # It's likely a root, but let's list it anyway to match user checks
                     orphans.append(s)
                else:
                    # Tools and LLMs generally shouldn't be root
                    print(f"  >>> FAILURE: {name} ({s['type']}) IS ORPHAN (Should be child)")
                    orphans.append(s)
            
            if "write_todos" in name and not pid:
                 pass

        
        if orphans:
            print("\n!!! WARNING: Potential Orphan Nodes Found !!!")
            for o in orphans:
                print(f"- {o['name']} ({o['type']})")
        else:
            print("\n>>> CLEAN TRACE: No unexpected orphans found. <<<")

if __name__ == "__main__":
    asyncio.run(verify_trace())
