from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import truststore
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse

# Use the OS certificate store (macOS Keychain) so corporate VPN CAs are trusted.
truststore.inject_into_ssl()

from samwise.config import Settings
from samwise.dispatch import Dispatcher
from samwise.handlers.act import ActHandler
from samwise.handlers.defer import DeferHandler
from samwise.handlers.notify import NotifyHandler
from samwise.models import ActivityItem, Disposition, HealthResponse, StatusSummary
from samwise.pipeline import Pipeline
from samwise.sensors.calendar import CalendarSensor
from samwise.sensors.github import GitHubSensor
from samwise.sensors.jira import JiraSensor

logger = logging.getLogger(__name__)

settings = Settings()

# Singletons set during lifespan
_pipeline: Pipeline | None = None
_github_sensor: GitHubSensor | None = None
_jira_sensor: JiraSensor | None = None
_calendar_sensor: CalendarSensor | None = None
_notify_handler: NotifyHandler | None = None
_defer_handler: DeferHandler | None = None
_act_handler: ActHandler | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    global _pipeline, _github_sensor, _jira_sensor, _calendar_sensor, _notify_handler, _defer_handler, _act_handler

    _github_sensor = GitHubSensor(settings)
    _jira_sensor = JiraSensor(settings)
    _calendar_sensor = CalendarSensor(settings)

    # Real handlers ---
    _notify_handler = NotifyHandler()
    _defer_handler = DeferHandler(settings.data_dir / "deferred.json")
    _act_handler = ActHandler(settings, _notify_handler)

    dispatcher = Dispatcher()
    dispatcher.register(Disposition.NOTIFY, _notify_handler.handle)
    dispatcher.register(Disposition.DEFER, _defer_handler.handle)
    dispatcher.register(Disposition.ACT, _act_handler.handle)

    _pipeline = Pipeline(
        sensors=[_github_sensor, _jira_sensor, _calendar_sensor],
        dispatcher=dispatcher,
    )

    token_path = settings.data_dir / "google_token.json"
    logger.info(
        "Samwise starting — GitHub: %s, Jira: %s, Calendar: %s",
        "active" if settings.github_token else "disabled (no token)",
        "active" if settings.jira_base_url else "disabled (no base URL)",
        "active" if token_path.exists() else "disabled (run make auth-google)",
    )

    await _pipeline.start(settings.poll_interval_seconds)

    yield

    await _pipeline.stop()
    await _act_handler.close()
    if _github_sensor:
        await _github_sensor.close()
    if _jira_sensor:
        await _jira_sensor.close()
    if _calendar_sensor:
        await _calendar_sensor.close()


app = FastAPI(title="Samwise", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------- Existing endpoints ----------


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


# ---------- SSE endpoint ----------


@app.get("/api/events")
async def events() -> StreamingResponse:
    """Server-Sent Events stream — pushes notify items in real-time."""
    if _notify_handler is None:
        return StreamingResponse(iter([]), media_type="text/event-stream")

    queue = _notify_handler.subscribe()

    async def event_stream() -> AsyncGenerator[str]:
        try:
            while True:
                item = await queue.get()
                yield f"data: {item.model_dump_json()}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if _notify_handler:
                _notify_handler.unsubscribe(queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------- Deferred endpoints ----------


@app.get("/api/deferred")
async def deferred() -> list[ActivityItem]:
    if _defer_handler is None:
        return []
    return _defer_handler.list_items()


@app.post("/api/deferred/flush")
async def flush_deferred() -> list[ActivityItem]:
    """Move all deferred items back into the activity feed."""
    if _defer_handler is None:
        return []
    return _defer_handler.flush()


# ---------- Ingest endpoint ----------


@app.post("/api/ingest")
async def ingest(items: list[ActivityItem]) -> list[ActivityItem]:
    """Accept externally-pushed items (e.g. from Jira via MCP) and run them through the pipeline."""
    if _pipeline is None:
        return []
    return await _pipeline.ingest(items)


def main() -> None:
    import socket

    import uvicorn

    logging.basicConfig(level=logging.INFO)

    port = settings.port
    # Auto-pick a free port if the configured one is in use.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex((settings.host, port)) == 0:
            # Port is occupied — let the OS assign one.
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as free:
                free.bind((settings.host, 0))
                port = free.getsockname()[1]
            logger.info("Port %d in use, auto-selected port %d", settings.port, port)

    # Structured line the extension watches for to know we're ready.
    print(f"SAMWISE_PORT={port}", flush=True)

    uvicorn.run(
        "samwise.server:app",
        host=settings.host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
