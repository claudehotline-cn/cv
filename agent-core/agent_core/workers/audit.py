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
    
    def __init__(self, event_bus: EventBus, persist_callback=None):
        self.event_bus = event_bus
        self.persist_callback = persist_callback
        self.running = False
        self.max_retries = 3
        
    async def start(self):
        """Start consuming events."""
        print("UUID-MARKER-FIXED-REALLY: AuditWorker Starting with Fixes", flush=True)
        self.running = True
        print(f"[AuditWorker] STARTING consumer on audit.events (BATCH MODE)", flush=True)
        _LOGGER.info("[AuditWorker] Starting audit consumer service (BATCH MODE)...")
        
        # Subscribe to audit topic
        iterator = self.event_bus.subscribe("audit.events", last_id="0")
        
        batch = []
        batch_size = 10
        batch_timeout = 0.05 # 50ms
        last_flush_time = time.time()
        
        try:
            print("[AuditWorker] Entering event loop", flush=True)
            
            # Simple batching implementation
            # Since iterator yields events, we can't easily timeout waiting for next event without asyncio.wait_for
            # But wait_for on every iteration is expensive.
            # A better approach for simple batching from async generator:
            # 1. Try to get events.
            # 2. If we have events, add to batch.
            # 3. Check flush condition.
            
            async for event in iterator:
                # print(f"[AuditWorker] Received event raw: {str(event)[:100]}", flush=True)
                if not self.running:
                    break
                
                batch.append(event)
                
                current_time = time.time()
                if len(batch) >= batch_size or (current_time - last_flush_time) >= batch_timeout:
                    await self.process_batch(batch)
                    batch = []
                    last_flush_time = current_time
            
            # Flush remaining
            if batch:
                 await self.process_batch(batch)

        except Exception as e:
            print(f"[AuditWorker] CRASHED: {e}", flush=True)
            _LOGGER.error(f"[AuditWorker] Consumer crashed: {e}")
            if self.running:
                pass

    async def stop(self):
        self.running = False
        
    async def process_batch(self, batch: list[Dict[str, Any]]):
        """Process a batch of audit events."""
        if not batch:
            return
            
        try:
            # DEBUG: Inspect batch type
            if batch:
                 print(f"[AuditWorker Debug] Batch count: {len(batch)}. First item type: {type(batch[0])}. Content: {batch[0]}", flush=True)

            # Pre-processing batch
            processed_batch = []
            for event in batch:
                # Parse if needed
                if isinstance(event, (str, bytes)):
                    try:
                        event = json.loads(event)
                    except Exception as e:
                        _LOGGER.error(f"[AuditWorker] Failed to parse event JSON: {e}")
                        continue
                
                # Enrich
                if "timestamp" not in event:
                    event["timestamp"] = time.time()
                
                # Log (maybe sample or summary?)
                print(f"AUDIT_LOG: {json.dumps(event, ensure_ascii=False)}", flush=True)
                processed_batch.append(event)
            
            if not processed_batch:
                return

            print(f"[AuditWorker] Processing batch of {len(processed_batch)} events", flush=True)
            
            if self.persist_callback:
                await self.persist_callback(processed_batch)
            
        except Exception as e:
            _LOGGER.error(f"[AuditWorker] Failed to process batch: {e}")

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
