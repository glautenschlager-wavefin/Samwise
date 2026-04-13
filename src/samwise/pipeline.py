from __future__ import annotations

import asyncio
import logging

from samwise.dispatch import Dispatcher
from samwise.models import ActivityItem, Disposition
from samwise.sensors.base import Sensor
from samwise.triage import triage

logger = logging.getLogger(__name__)


class Pipeline:
    """Sense → Triage → Dispatch loop.

    Coordinates sensors, triage rules, and dispatch handlers into
    a single polling loop. Maintains a cache of the latest triaged
    items for the API to serve.
    """

    def __init__(self, sensors: list[Sensor], dispatcher: Dispatcher) -> None:
        self._sensors = sensors
        self._dispatcher = dispatcher
        self._cache: list[ActivityItem] = []
        self._deferred: list[ActivityItem] = []
        self._task: asyncio.Task[None] | None = None

    @property
    def activity(self) -> list[ActivityItem]:
        """Items to show in the activity feed (notify disposition, sorted by time)."""
        return list(self._cache)

    @property
    def deferred(self) -> list[ActivityItem]:
        """Items that were deferred for later."""
        return list(self._deferred)

    async def run_once(self) -> None:
        """Execute one full sense→triage→dispatch cycle."""
        # Sense: collect from all sensors
        raw_items: list[ActivityItem] = []
        for sensor in self._sensors:
            try:
                items = await sensor.poll()
                raw_items.extend(items)
            except Exception:
                logger.exception("Sensor %s failed", type(sensor).__name__)

        logger.info("Sensed %d raw items from %d sensors", len(raw_items), len(self._sensors))

        # Triage: classify urgency and disposition
        triaged = triage(raw_items)

        # Update caches before dispatch
        self._cache = sorted(
            [i for i in triaged if i.disposition != Disposition.DEFER],
            key=lambda i: (i.urgency != "high", i.timestamp),
            reverse=True,
        )
        self._deferred = [i for i in triaged if i.disposition == Disposition.DEFER]

        # Dispatch: route to handlers
        await self._dispatcher.dispatch(triaged)

    async def start(self, interval_seconds: int) -> None:
        """Start the background polling loop."""
        # Initial run
        await self.run_once()
        # Schedule recurring
        self._task = asyncio.create_task(self._loop(interval_seconds))

    async def _loop(self, interval: int) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self.run_once()
            except Exception:
                logger.exception("Pipeline cycle failed")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
