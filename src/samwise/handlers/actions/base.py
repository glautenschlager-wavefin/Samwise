from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum

from samwise.models import ActivityItem


class SafetyLevel(StrEnum):
    """How autonomously an action is allowed to run."""

    AUTO = "auto"  # reversible/low-risk — runs without asking
    CONFIRM = "confirm"  # risky — gated behind an explicit opt-in setting


class Action(ABC):
    """A single autonomous capability Samwise can perform.

    Each action owns its own matching logic, its enable/safety gating,
    and the fallback notification it emits when it is not permitted to run.
    The registry stays dumb: it only routes an item to the first action
    whose :meth:`matches` returns ``True``.
    """

    #: Stable identifier (used in result ids and logs).
    name: str
    #: How autonomously this action may run.
    safety: SafetyLevel

    @abstractmethod
    def matches(self, item: ActivityItem) -> bool:
        """Return True if this action can handle *item*."""

    @abstractmethod
    async def execute(self, item: ActivityItem) -> ActivityItem:
        """Perform the action and return a result item to notify the user.

        Implementations are responsible for their own enable-check: if the
        relevant setting is disabled they should return a "ready to do X"
        notification instead of performing the side effect.
        """

    async def close(self) -> None:
        """Release any resources (HTTP clients, etc.). Override if needed."""
        return None
