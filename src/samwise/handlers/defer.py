from __future__ import annotations

import json
import logging
from pathlib import Path

from samwise.models import ActivityItem

logger = logging.getLogger(__name__)


class DeferHandler:
    """Persist deferred items to a JSON file so they survive restarts."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._items: list[ActivityItem] = []
        self._load()

    async def handle(self, items: list[ActivityItem]) -> None:
        self._items.extend(items)
        self._save()
        logger.info("Deferred %d items (total: %d)", len(items), len(self._items))

    def list_items(self) -> list[ActivityItem]:
        return list(self._items)

    def flush(self) -> list[ActivityItem]:
        """Return all deferred items and clear the store."""
        items = list(self._items)
        self._items.clear()
        self._save()
        logger.info("Flushed %d deferred items", len(items))
        return items

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            self._items = [ActivityItem.model_validate(d) for d in data]
            logger.info("Loaded %d deferred items from %s", len(self._items), self._path)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Corrupt deferred file %s — starting fresh", self._path)
            self._items = []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                [i.model_dump(mode="json") for i in self._items],
                indent=2,
                default=str,
            )
        )
