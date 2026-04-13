from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from samwise.config import Settings
from samwise.dispatch import Dispatcher
from samwise.models import ActivityItem, Disposition, HealthResponse, StatusSummary
from samwise.pipeline import Pipeline
from samwise.sensors.github import GitHubSensor

logger = logging.getLogger(__name__)

settings = Settings()

# The pipeline is the core of Samwise — sense → triage → dispatch.
_pipeline: Pipeline | None = None
_github_sensor: GitHubSensor | None = None


async def _notify_handler(items: list[ActivityItem]) -> None:
    """Handle items that should be pushed to the user.

    For now, this is a no-op — the API serves them from the pipeline cache.
    Later this can push via WebSocket, system notifications, etc.
    """
    logger.info("Notify: %d items ready for user", len(items))


async def _defer_handler(items: list[ActivityItem]) -> None:
    """Handle items that should be stored for later."""
    logger.info("Deferred: %d items stored for later", len(items))


async def _act_handler(items: list[ActivityItem]) -> None:
    """Handle items Samwise should act on autonomously.

    Placeholder — future home of autonomous task execution.
    """
    for item in items:
        logger.info("Would act on: %s — %s", item.title, item.detail)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    global _pipeline, _github_sensor

    _github_sensor = GitHubSensor(settings)

    dispatcher = Dispatcher()
    dispatcher.register(Disposition.NOTIFY, _notify_handler)
    dispatcher.register(Disposition.DEFER, _defer_handler)
    dispatcher.register(Disposition.ACT, _act_handler)

    _pipeline = Pipeline(
        sensors=[_github_sensor],
        dispatcher=dispatcher,
    )

    await _pipeline.start(settings.poll_interval_seconds)

    yield

    await _pipeline.stop()
    if _github_sensor:
        await _github_sensor.close()


app = FastAPI(title="Samwise", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version="0.1.0")


@app.get("/api/activity")
async def activity() -> list[ActivityItem]:
    if _pipeline is None:
        return []
    return _pipeline.activity


@app.get("/api/status")
async def status() -> StatusSummary:
    items = _pipeline.activity if _pipeline else []
    deferred_count = len(_pipeline.deferred) if _pipeline else 0

    high = sum(1 for i in items if i.urgency == "high")
    total = len(items)

    parts = []
    if high:
        parts.append(f"{high} urgent")
    parts.append(f"{total} active")
    if deferred_count:
        parts.append(f"{deferred_count} deferred")

    detail = " · ".join(parts)

    return StatusSummary(
        text=f"$(rocket) Samwise: {detail}",
        tooltip=f"{detail}\nClick to open Activity Feed",
    )


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "samwise.server:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
