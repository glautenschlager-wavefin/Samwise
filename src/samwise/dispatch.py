from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from samwise.models import ActivityItem, Disposition

logger = logging.getLogger(__name__)

DispatchHandler = Callable[[list[ActivityItem]], Coroutine[Any, Any, None]]


class Dispatcher:
    """Routes triaged items to handlers based on their disposition."""

    def __init__(self) -> None:
        self._handlers: dict[Disposition, DispatchHandler] = {}

    def register(self, disposition: Disposition, handler: DispatchHandler) -> None:
        self._handlers[disposition] = handler

    async def dispatch(self, items: list[ActivityItem]) -> None:
        """Group items by disposition and call the appropriate handler for each group."""
        groups: dict[Disposition, list[ActivityItem]] = {d: [] for d in Disposition}
        for item in items:
            groups[item.disposition].append(item)

        for disposition, group in groups.items():
            if not group:
                continue
            handler = self._handlers.get(disposition)
            if handler:
                logger.info("Dispatching %d items to %s handler", len(group), disposition)
                try:
                    await handler(group)
                except Exception:
                    logger.exception("Error in %s handler", disposition)
            else:
                logger.warning("No handler for disposition %s (%d items dropped)", disposition, len(group))
