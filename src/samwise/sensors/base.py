from __future__ import annotations

from abc import ABC, abstractmethod

from samwise.models import ActivityItem


class Sensor(ABC):
    @abstractmethod
    async def poll(self) -> list[ActivityItem]:
        """Poll for new activity items."""
        ...
