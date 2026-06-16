from __future__ import annotations

import logging
from datetime import UTC, datetime

from samwise.config import Settings
from samwise.handlers.actions import ActionRegistry, build_default_registry
from samwise.handlers.notify import NotifyHandler
from samwise.models import ActivityItem

logger = logging.getLogger(__name__)


class ActHandler:
    """Execute autonomous actions via the action registry.

    Each ACT item is routed to the first matching :class:`Action`
    (e.g. auto-fix lint, merge an approved PR). Results are pushed back
    through the notify handler so the user sees what Samwise did on
    their behalf.
    """

    def __init__(
        self,
        settings: Settings,
        notify: NotifyHandler,
        registry: ActionRegistry | None = None,
    ) -> None:
        self._settings = settings
        self._notify = notify
        self._registry = registry or build_default_registry(settings)

    async def handle(self, items: list[ActivityItem]) -> None:
        for item in items:
            result = await self._execute(item)
            await self._notify.handle([result])

    async def close(self) -> None:
        await self._registry.close()

    async def _execute(self, item: ActivityItem) -> ActivityItem:
        action = self._registry.find(item)
        if action is None:
            logger.info("No automated action for: %s", item.title)
            return ActivityItem(
                id=f"act-skip-{item.id}",
                category=item.category,
                icon="⏭️",
                title=f"Skipped: {item.title}",
                detail="No automated action available for this item type",
                timestamp=datetime.now(UTC),
            )

        logger.info("Running action '%s' for: %s", action.name, item.title)
        return await action.execute(item)
