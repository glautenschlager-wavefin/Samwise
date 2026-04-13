from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from samwise.config import Settings
from samwise.models import ActivityItem, HealthResponse, StatusSummary
from samwise.sensors.github import GitHubSensor

logger = logging.getLogger(__name__)

settings = Settings()

# Shared state: cached activity items from the latest poll
_activity_cache: list[ActivityItem] = []
_poll_task: asyncio.Task[None] | None = None
_github_sensor: GitHubSensor | None = None


async def _poll_loop(sensor: GitHubSensor, interval: int) -> None:
    global _activity_cache
    while True:
        try:
            logger.info("Polling GitHub...")
            items = await sensor.poll()
            _activity_cache = sorted(items, key=lambda i: i.timestamp, reverse=True)
            logger.info("Poll complete: %d items", len(_activity_cache))
        except Exception:
            logger.exception("Unexpected error in poll loop")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    global _poll_task, _github_sensor

    _github_sensor = GitHubSensor(settings)

    # Run an initial poll immediately
    try:
        items = await _github_sensor.poll()
        global _activity_cache
        _activity_cache = sorted(items, key=lambda i: i.timestamp, reverse=True)
    except Exception:
        logger.exception("Initial poll failed")

    # Start background polling
    _poll_task = asyncio.create_task(
        _poll_loop(_github_sensor, settings.poll_interval_seconds)
    )

    yield

    # Shutdown
    if _poll_task:
        _poll_task.cancel()
        try:
            await _poll_task
        except asyncio.CancelledError:
            pass
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
    return _activity_cache


@app.get("/api/status")
async def status() -> StatusSummary:
    total = len(_activity_cache)
    ci_failures = sum(1 for i in _activity_cache if "CI" in i.title or i.icon == "🔴")
    reviews = sum(1 for i in _activity_cache if "Review" in i.title or "review" in i.title)
    approved = sum(1 for i in _activity_cache if "approved" in i.title.lower())

    parts = []
    if approved:
        parts.append(f"{approved} approved")
    if ci_failures:
        parts.append(f"{ci_failures} CI failing")
    if reviews:
        parts.append(f"{reviews} review pending")
    parts.append(f"{total} total")

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
