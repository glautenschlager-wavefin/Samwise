from __future__ import annotations

import logging

from samwise.handlers.actions.base import Action
from samwise.models import ActivityItem

logger = logging.getLogger(__name__)


class ActionRegistry:
    """Routes triaged ACT items to the first matching :class:`Action`."""

    def __init__(self, actions: list[Action]) -> None:
        self._actions = actions

    def find(self, item: ActivityItem) -> Action | None:
        """Return the first action that matches *item*, or None."""
        for action in self._actions:
            if action.matches(item):
                return action
        return None

    async def close(self) -> None:
        for action in self._actions:
            await action.close()
