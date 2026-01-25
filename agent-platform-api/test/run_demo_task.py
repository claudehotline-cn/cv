import asyncio
import httpx
import sys
import json

BASE_URL = "http://agent-api:8000"

async def run_demo_task():
    async with httpx.AsyncClient(timeout=300.0) as client:
        # 1. Get List Agents
        resp = await client.get(f"{BASE_URL}/agents/")
        agents = resp.json()
        agent = next((a for a in agents if a.get("builtin_key") == "data_agent"), None)
        if not agent:
             print("Data Agent not found")
             sys.exit(1)
        agent_id = agent["id"]

        # 2. Create Session
        resp = await client.post(f"{BASE_URL}/sessions/", json={"agent_id": agent_id, "title": "City Sales Demo"})
        session_id = resp.json()["id"]
        print(f"Session Created: {session_id}")
        
        # 3. Send Task
        # Prompt: "按城市统计每月订单总金额，绘制一个折线图"
        message = "按城市统计每月订单总金额，绘制一个折线图"
        print(f"Sending Prompt: {message}")
        
        async with client.stream("POST", f"{BASE_URL}/sessions/{session_id}/chat", json={"message": message}) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if "__interrupt__" in data:
                            print("\n>>> HITL INTERRUPT RECEIVED <<<")
                            print(json.dumps(data["__interrupt__"], indent=2, ensure_ascii=False))
                            break
                        
                        # Print thinking or tool logs for visibility
                        if data.get("type") == "reasoning": 
                             print(f"[Thinking] {data.get('reasoning')[:100]}...", end="\r")
                        elif data.get("type") == "tool":
                             print(f"[Tool] {data.get('name')}")
                        elif data.get("type") == "content":
                             print(f"[Content] {data.get('content')}")
                             
                    except:
                        pass
                        
if __name__ == "__main__":
    asyncio.run(run_demo_task())
