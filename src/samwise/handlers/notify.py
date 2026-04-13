from __future__ import annotations

import asyncio
import logging
from typing import Any

from samwise.models import ActivityItem

logger = logging.getLogger(__name__)


class NotifyHandler:
    """Push notifications to connected SSE subscribers.

    Each subscriber gets an asyncio.Queue.  The SSE endpoint reads from the
    queue and streams events in ``text/event-stream`` format.
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[ActivityItem]] = []

    async def handle(self, items: list[ActivityItem]) -> None:
        for item in items:
            logger.info("Notify → %s (%s)", item.title, item.urgency)
            dead: list[asyncio.Queue[Any]] = []
            for queue in self._subscribers:
                try:
                    queue.put_nowait(item)
                except asyncio.QueueFull:
                    dead.append(queue)
            # Drop slow subscribers
            for q in dead:
                self._subscribers.remove(q)

    def subscribe(self) -> asyncio.Queue[ActivityItem]:
        """Create a new subscriber queue (max 256 buffered events)."""
        queue: asyncio.Queue[ActivityItem] = asyncio.Queue(maxsize=256)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[ActivityItem]) -> None:
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass
