import asyncio
import httpx
import uuid
import sys
import json

# Adjust base URL if needed. 
BASE_URL = "http://agent-api:8000"

async def test_chat():
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. List Agents to get a valid agent_id
        print("--- 1. Getting Agents ---")
        resp = await client.get(f"{BASE_URL}/agents/")
        if resp.status_code != 200:
            print(f"Failed to list agents: {resp.text}")
            return
            
        agents = resp.json()
        if not agents:
            print("No agents found via API.")
            return
            
        # Use the first available agent
        agent = agents[0]
        agent_id = agent["id"]
        print(f"Using Agent: {agent['name']} ({agent_id})")
        
        # 2. Create Session
        print("--- 2. Creating Session ---")
        resp = await client.post(f"{BASE_URL}/sessions/", json={"agent_id": agent_id, "title": "E2E Test"})
        if resp.status_code != 200:
            print(f"Failed to create session: {resp.text}")
            return
            
        session = resp.json()
        session_id = session["id"]
        print(f"Session Created: {session_id}")
        
        # 3. Send Chat
        print("--- 3. Sending Chat Message ---")
        message = "Hello, please list tables."
        
        # Streaming response
        async with client.stream("POST", f"{BASE_URL}/sessions/{session_id}/chat", json={"message": message}) as response:
            if response.status_code != 200:
                 print(f"Chat failed: {response.status_code}")
                 print(await response.read())
                 return

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]": break
                    try:
                        data = json.loads(data_str)
                        # Just print type or content summary
                        if isinstance(data, list):
                            print(f"Stream Chunk: {data[0].get('type')}")
                        elif isinstance(data, dict):
                             print(f"Stream Event: {data.get('type')}")
                    except:
                        pass
        
        print("Chat completed.")

        # 4. Verify Audit
        # We can hit the audit API
        print("--- 4. Verifying Audit Log ---")
        await asyncio.sleep(2) # Wait for async audit processing
        
        resp = await client.get(f"{BASE_URL}/audit/runs?page=1&size=10")
        if resp.status_code == 200:
            runs = resp.json().get("items", [])
            # Find our session run
            matching = [r for r in runs if r.get("conversation_id") == session_id]
            if matching:
                run = matching[0]
                print(f"SUCCESS: Found Audit Run {run['run_id']} with status {run['status']}")
                
                # Fetch full run details to check timeline
                print(f"--- Fetching detailed run info for {run['run_id']} ---")
                run_detail_resp = await client.get(f"{BASE_URL}/audit/runs/{run['run_id']}")
                if run_detail_resp.status_code == 200:
                    run_detail = run_detail_resp.json()
                    # Dump relevant parts of the timeline/steps
                    print(json.dumps(run_detail, indent=2))
                else:
                    print(f"Failed to get run details: {run_detail_resp.status_code}")
            else:
                print("FAILURE: No audit run found for this session.")
                print(f"Runs found: {len(runs)}")
        else:
             print(f"Audit API failed: {resp.text}")

if __name__ == "__main__":
    asyncio.run(test_chat())
