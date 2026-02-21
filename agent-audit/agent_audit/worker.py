import logging
import json
import os
import time
import asyncio
from typing import Any, Callable, Dict, List, Optional, Protocol

_LOGGER = logging.getLogger(__name__)


class AuditEventSource(Protocol):
    async def subscribe(self, topic: str, last_id: str = "$"):
        ...

class AuditWorker:
    """
    Worker that consumes audit events from the Event Bus and writes them to persistent storage.
    
    For MVP, we write to a log file or stdout.
    In Production, this would write to Postgres 'audit_logs' table.
    """
    
    def __init__(
        self,
        event_bus: AuditEventSource,
        persist_callback: Optional[Callable[[List[Dict[str, Any]]], Any]] = None,
    ):
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

        topic = "audit.events"
        cursor_key = os.getenv("AUDIT_CURSOR_KEY", f"{topic}:last_id")

        # Durable cursor (best-effort): store last processed Redis Stream entry id in Redis.
        # This avoids replaying the full stream on restarts and prevents long catch-up delays.
        checkpoint_redis = None
        redis_url = getattr(self.event_bus, "redis_url", None)
        if isinstance(redis_url, str) and redis_url:
            try:
                import redis.asyncio as aioredis

                checkpoint_redis = aioredis.from_url(redis_url, decode_responses=True)
            except Exception:
                checkpoint_redis = None

        start_id = os.getenv("AUDIT_WORKER_START_ID")
        if not start_id and checkpoint_redis is not None:
            try:
                start_id = await checkpoint_redis.get(cursor_key)
            except Exception:
                start_id = None
        # Treat "$" as an uninitialized cursor.
        if start_id == "$":
            start_id = None
        if not start_id and checkpoint_redis is not None:
            # Initialize cursor to the current tail to avoid replaying a huge backlog.
            # This still allows processing all *new* events emitted after the worker starts.
            try:
                info = await checkpoint_redis.xinfo_stream(topic)
                start_id = info.get("last-generated-id") if isinstance(info, dict) else None
            except Exception:
                start_id = None
            if start_id:
                try:
                    await checkpoint_redis.set(cursor_key, start_id)
                except Exception:
                    pass
        if not start_id:
            # Fallback: Redis semantics for "new only". (May miss events already in stream.)
            start_id = "$"

        subscribe_with_ids = getattr(self.event_bus, "subscribe_with_ids", None)
        if callable(subscribe_with_ids):
            iterator = subscribe_with_ids(topic, last_id=start_id)
            yields_ids = True
        else:
            iterator = self.event_bus.subscribe(topic, last_id=start_id)
            yields_ids = False
        
        batch = []
        batch_size = 10
        batch_timeout = 0.05 # 50ms
        last_flush_time = time.time()
        batch_last_stream_id: str | None = None
        
        try:
            print("[AuditWorker] Entering event loop", flush=True)
            
            # NOTE: If we only flush on *new event arrival*, the last few events in a burst
            # can get stuck in memory forever (until another event arrives). We therefore
            # use a timeout-driven read loop to ensure the batch flushes on inactivity.
            anext = iterator.__anext__  # type: ignore[attr-defined]
            while self.running:
                try:
                    item = await asyncio.wait_for(anext(), timeout=batch_timeout)
                except asyncio.TimeoutError:
                    # No new events: flush pending batch if any.
                    if batch and (time.time() - last_flush_time) >= batch_timeout:
                        ok = await self.process_batch(batch)
                        if ok and checkpoint_redis is not None and batch_last_stream_id:
                            try:
                                await checkpoint_redis.set(cursor_key, batch_last_stream_id)
                            except Exception:
                                pass
                        batch = []
                        batch_last_stream_id = None
                        last_flush_time = time.time()
                    continue
                except StopAsyncIteration:
                    break

                if yields_ids:
                    stream_id, event = item
                    batch_last_stream_id = stream_id
                else:
                    event = item

                batch.append(event)
                if len(batch) >= batch_size:
                    ok = await self.process_batch(batch)
                    if ok and checkpoint_redis is not None and batch_last_stream_id:
                        try:
                            await checkpoint_redis.set(cursor_key, batch_last_stream_id)
                        except Exception:
                            pass
                    batch = []
                    batch_last_stream_id = None
                    last_flush_time = time.time()
            
            # Flush remaining
            if batch:
                ok = await self.process_batch(batch)
                if ok and checkpoint_redis is not None and batch_last_stream_id:
                    try:
                        await checkpoint_redis.set(cursor_key, batch_last_stream_id)
                    except Exception:
                        pass

        except Exception as e:
            print(f"[AuditWorker] CRASHED: {e}", flush=True)
            _LOGGER.error(f"[AuditWorker] Consumer crashed: {e}")
            if self.running:
                pass
        finally:
            if checkpoint_redis is not None:
                try:
                    await checkpoint_redis.aclose()
                except Exception:
                    pass

    async def stop(self):
        self.running = False
        
    async def process_batch(self, batch: list[Dict[str, Any]]) -> bool:
        """Process a batch of audit events."""
        if not batch:
            return True
            
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
                return True

            print(f"[AuditWorker] Processing batch of {len(processed_batch)} events", flush=True)
            
            if self.persist_callback:
                await self.persist_callback(processed_batch)
            return True
            
        except Exception as e:
            _LOGGER.error(f"[AuditWorker] Failed to process batch: {e}")
            return False

__all__ = ["AuditWorker", "AuditEventSource"]
