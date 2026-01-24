import asyncio
import logging
import json
import time
from typing import Dict, Any

from agent_core.events import EventBus, RedisEventBus
from agent_core.settings import get_settings

_LOGGER = logging.getLogger(__name__)

class AuditWorker:
    """
    Worker that consumes audit events from the Event Bus and writes them to persistent storage.
    
    For MVP, we write to a log file or stdout.
    In Production, this would write to Postgres 'audit_logs' table.
    """
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.running = False
        self.max_retries = 3
        
    async def start(self):
        """Start consuming events."""
        self.running = True
        _LOGGER.info("[AuditWorker] Starting audit consumer service...")
        
        # Subscribe to audit topic
        # In Redis Streams, we usually use Consumer Groups for reliable delivery.
        # agent_core.events.RedisEventBus.subscribe is a simple iterator wrapper around xread.
        # For production robustness, we should use xreadgroup, but for now we reuse the existing simple subscription interface.
        
        iterator = self.event_bus.subscribe("agent:audit_events")
        
        try:
            async for event in iterator:
                if not self.running:
                    break
                await self.process_event(event)
        except Exception as e:
            _LOGGER.error(f"[AuditWorker] Consumer crashed: {e}")
            if self.running:
                # Simple restart logic could go here
                pass

    async def stop(self):
        self.running = False
        
    async def process_event(self, event: Dict[str, Any]):
        """
        Process a single audit event.
        Expected format:
        {
            "type": "tool_start" | "tool_end" | ...,
            "timestamp": float,
            "user_id": str,
            "trace_id": str,
            "data": {...}
        }
        """
        try:
            # Here we would insert into DB
            # For now, we simulate by logging Structured JSON
            
            # Enrich/Normalize
            if "timestamp" not in event:
                event["timestamp"] = time.time()
                
            log_entry = json.dumps(event, ensure_ascii=False)
            
            # Print to stdout (docker logs captured by Fluentd/Promtail)
            # Prefix with AUDIT_LOG for easy grep
            print(f"AUDIT_LOG: {log_entry}")
            
            # Simulate DB Write Latency
            # await asyncio.sleep(0.01)
            
        except Exception as e:
            _LOGGER.error(f"[AuditWorker] Failed to process event: {e}, Event: {event}")

async def main():
    """Entrypoint for standalone worker process."""
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    
    if not settings.redis_url:
        _LOGGER.error("REDIS_URL not set, exiting.")
        return

    # Initialize Redis Bus
    bus = RedisEventBus(redis_url=settings.redis_url)
    
    worker = AuditWorker(bus)
    
    # Graceful shutdown handler could be added here
    await worker.start()

if __name__ == "__main__":
    asyncio.run(main())
