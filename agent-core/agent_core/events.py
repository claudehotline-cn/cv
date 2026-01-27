"""Event Bus Infrastructure for Agent Platform.

Provides abstract EventBus interface and concrete implementations for:
- MemoryEventBus: For single-process communication (using asyncio.Queue)
- RedisEventBus: For distributed communication (using Redis Streams)
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, AsyncIterator, List, Optional
import asyncio
import json
import logging

_LOGGER = logging.getLogger("agent_core.events")

class EventBus(ABC):
    """Abstract Event Bus interface."""
    
    @abstractmethod
    async def publish(self, topic: str, event: Dict[str, Any]) -> None:
        """Publish an event to a topic."""
        pass

    @abstractmethod
    async def subscribe(self, topic: str, last_id: str = "$") -> AsyncIterator[Dict[str, Any]]:
        """Subscribe to a topic and yield events."""
        pass


class MemoryEventBus(EventBus):
    """In-memory Event Bus using asyncio Queues.
    
    Suitable for single-process testing or local deployments.
    Broadcasting is implemented by maintaining a list of active queues per topic.
    """
    
    def __init__(self):
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        
    async def publish(self, topic: str, event: Dict[str, Any]) -> None:
        async with self._lock:
            if topic in self._subscribers:
                # Provide a shallow copy to iterate over
                queues = list(self._subscribers[topic])
                for q in queues:
                    await q.put(event)
    
    async def subscribe(self, topic: str, last_id: str = "$") -> AsyncIterator[Dict[str, Any]]:
        q = asyncio.Queue()
        
        async with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = []
            self._subscribers[topic].append(q)
            
        try:
            while True:
                event = await q.get()
                yield event
        finally:
            async with self._lock:
                if topic in self._subscribers:
                    self._subscribers[topic].remove(q)
                    if not self._subscribers[topic]:
                        del self._subscribers[topic]


class RedisEventBus(EventBus):
    """Redis Stream based Event Bus.
    
    Suitable for distributed deployments (Worker <-> API).
    """
    
    def __init__(self, redis_url: str):
        import redis.asyncio as aioredis
        self.redis = aioredis.from_url(redis_url, decode_responses=False)
        self.redis_url = redis_url
        
    async def publish(self, topic: str, event: Dict[str, Any]) -> None:
        """Publish to Redis Stream.
        
        Event dict is flattened:
        - 'type' -> message type (e.g. 'chunk', 'progress')
        - 'data' -> payload (JSON string or bytes)
        """
        # Ensure data is properly serialized for Redis
        # Conventional mapping used in worker.py:
        # type: ...
        # data: ...
        
        # If the event follows standard structure {type: ..., data: ...}, use it.
        # Otherwise, wrap it? Current worker.py manually constructs dict.
        # Let's support arbitrary dicts by serializing values to strings if needed.
        
        payload = {}
        for k, v in event.items():
            if isinstance(v, (str, bytes, int, float)):
                payload[k] = v
            else:
                payload[k] = json.dumps(v)
                
        await self.redis.xadd(topic, payload, maxlen=1000)

    async def subscribe(self, topic: str, last_id: str = "$") -> AsyncIterator[Dict[str, Any]]:
        """Yields dicts from Redis Stream.
        
        Values are decoded to strings. 'data' field is NOT automatically JSON parsed here,
        to keep parity with how frontend reads it (or we can parse it).
        
        The existing route implementation yields:
        { "type": ..., "data": ... }
        """
        # Local redis connection for subscription to avoid sharing issues if reuse is tricky
        import redis.asyncio as aioredis
        consumer_redis = aioredis.from_url(self.redis_url, decode_responses=True)
        
        current_id = last_id
        try:
            while True:
                # Block for 1 second
                streams = await consumer_redis.xread({topic: current_id}, count=10, block=1000)
                
                if not streams:
                    # needed to yield control or check disconnects?
                    # xread waits, so if it returns empty, it timed out (1s)
                    # Yield nothing or continue loop?
                    # Since this is an async generator, we can just continue to loop.
                    # Caller usually expects us to yield when event arrives.
                    # We can yield a "heartbeat" or just wait.
                    # To allow caller to cancel, we just rely on async generator exit.
                    continue
                    
                for stream_name, events in streams:
                    for event_id, fields in events:
                        current_id = event_id
                        yield fields
        finally:
            await consumer_redis.close()

    async def close(self):
        await self.redis.close()

from agent_audit.emitter import AuditEmitter
