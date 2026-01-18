"""Infrastructure - Event Emitter implementations.

SSE 事件发送器实现。
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..domain.entities import StreamEvent

_LOGGER = logging.getLogger(__name__)


class SSEEmitter:
    """SSE 事件发送器 - 实现 IEventEmitter 接口。
    
    用于将事件流式发送到客户端。
    """
    
    def __init__(self) -> None:
        self._queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        self._closed = False
    
    async def emit(self, event: "StreamEvent") -> None:
        """发送单个事件到队列。"""
        if not self._closed:
            await self._queue.put(event)
    
    async def close(self) -> None:
        """关闭发送器，发送结束信号。"""
        self._closed = True
        await self._queue.put(None)  # 结束信号
    
    async def __aiter__(self):
        """异步迭代器，用于流式响应。"""
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event.to_sse()


class EventCollector:
    """事件收集器 - 用于测试和调试。
    
    收集所有事件到列表中。
    """
    
    def __init__(self) -> None:
        self.events: list["StreamEvent"] = []
        self._closed = False
    
    async def emit(self, event: "StreamEvent") -> None:
        """收集事件。"""
        if not self._closed:
            self.events.append(event)
    
    async def close(self) -> None:
        """标记为已关闭。"""
        self._closed = True
