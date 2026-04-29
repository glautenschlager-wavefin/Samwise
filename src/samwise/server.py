from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel as PydanticBaseModel
from starlette.responses import HTMLResponse, StreamingResponse

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
from samwise.sensors.project import ProjectSensor
from samwise.sensors.workspace import WorkspaceSensor

logger = logging.getLogger(__name__)

settings = Settings()

# ---------- Google OAuth state ----------
# Holds the pending OAuth flow object while the user authorises in the browser.
_pending_oauth_flow: Any = None  # InstalledAppFlow (lazy import)
_actual_port: int = settings.port  # Updated in main() after port resolution

# Singletons set during lifespan
_pipeline: Pipeline | None = None
_github_sensor: GitHubSensor | None = None
_jira_sensor: JiraSensor | None = None
_calendar_sensor: CalendarSensor | None = None
_project_sensor: ProjectSensor | None = None
_workspace_sensor: WorkspaceSensor | None = None
_notify_handler: NotifyHandler | None = None
_defer_handler: DeferHandler | None = None
_act_handler: ActHandler | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    global _pipeline, _github_sensor, _jira_sensor, _calendar_sensor, _project_sensor, _workspace_sensor, _notify_handler, _defer_handler, _act_handler

    _github_sensor = GitHubSensor(settings)
    _jira_sensor = JiraSensor(settings)
    _calendar_sensor = CalendarSensor(settings)
    _project_sensor = ProjectSensor(settings)
    _workspace_sensor = WorkspaceSensor(settings)

    # Real handlers ---
    _notify_handler = NotifyHandler()
    _defer_handler = DeferHandler(settings.data_dir / "deferred.json")
    _act_handler = ActHandler(settings, _notify_handler)

    dispatcher = Dispatcher()
    dispatcher.register(Disposition.NOTIFY, _notify_handler.handle)
    dispatcher.register(Disposition.DEFER, _defer_handler.handle)
    dispatcher.register(Disposition.ACT, _act_handler.handle)

    _pipeline = Pipeline(
        sensors=[_github_sensor, _jira_sensor, _calendar_sensor, _project_sensor, _workspace_sensor],
        dispatcher=dispatcher,
    )

    token_path = settings.data_dir / "google_token.json"
    logger.info(
        "Samwise starting — GitHub: %s, Jira: %s, Calendar: %s, Projects: %s, Workspace: %s",
        "active" if settings.github_token else "disabled (no token)",
        "active" if settings.jira_base_url else "disabled (no base URL)",
        "active" if token_path.exists() else "disabled (run 'Samwise: Connect Google Calendar')",
        f"{len(settings.project_repos)} repos" if settings.project_repos else "disabled (no repos configured)",
        f"{len(settings.workspace_roots)} root(s)" if settings.workspace_roots else "disabled (no workspace)",
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
    if _project_sensor:
        await _project_sensor.close()
    if _workspace_sensor:
        await _workspace_sensor.close()


app = FastAPI(title="Samwise", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PATCH"],
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


# ---------- Project endpoints ----------

_github_http: httpx.AsyncClient | None = None


def _get_github_http() -> httpx.AsyncClient:
    global _github_http
    if _github_http is None:
        _github_http = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {settings.github_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15.0,
        )
    return _github_http


class ProjectSummary(PydanticBaseModel):
    repo: str
    last_push: str | None = None
    idle_days: int = 0
    stale: bool = False
    open_issues: int = 0


@app.get("/api/projects")
async def list_projects() -> list[ProjectSummary]:
    """Health dashboard for tracked side-project repos."""
    from datetime import UTC, datetime, timedelta

    repos = settings.project_repos
    if not repos:
        return []

    client = _get_github_http()
    results: list[ProjectSummary] = []
    now = datetime.now(UTC)
    threshold = timedelta(days=settings.project_staleness_days)

    for repo in repos:
        try:
            resp = await client.get(f"/repos/{repo}")
            resp.raise_for_status()
            data = resp.json()
            pushed_at_str = data.get("pushed_at")
            idle_days = 0
            stale = False
            if pushed_at_str:
                pushed_at = datetime.fromisoformat(pushed_at_str)
                idle_days = (now - pushed_at).days
                stale = (now - pushed_at) > threshold

            results.append(
                ProjectSummary(
                    repo=repo,
                    last_push=pushed_at_str,
                    idle_days=idle_days,
                    stale=stale,
                    open_issues=data.get("open_issues_count", 0),
                )
            )
        except httpx.HTTPError:
            logger.warning("Failed to fetch project info for %s", repo)
            results.append(ProjectSummary(repo=repo))

    return results


@app.get("/api/projects/{owner}/{repo}/issues")
async def list_project_issues(
    owner: str,
    repo: str,
    state: str = Query("open"),
) -> list[dict]:
    """List issues for a tracked project repo."""
    client = _get_github_http()
    resp = await client.get(
        f"/repos/{owner}/{repo}/issues",
        params={"state": state, "per_page": "30", "sort": "updated", "direction": "desc"},
    )
    resp.raise_for_status()
    # Filter out pull requests (GitHub API returns them mixed in)
    return [i for i in resp.json() if "pull_request" not in i]


class CreateIssueRequest(PydanticBaseModel):
    title: str
    body: str = ""
    labels: list[str] = []
    assignee: str | None = None


@app.post("/api/projects/{owner}/{repo}/issues")
async def create_project_issue(
    owner: str,
    repo: str,
    req: CreateIssueRequest,
) -> dict:
    """Create a new issue on a tracked project repo."""
    client = _get_github_http()
    payload: dict = {"title": req.title}
    if req.body:
        payload["body"] = req.body
    if req.labels:
        payload["labels"] = req.labels
    if req.assignee:
        payload["assignees"] = [req.assignee]

    resp = await client.post(f"/repos/{owner}/{repo}/issues", json=payload)
    resp.raise_for_status()
    return resp.json()


class UpdateIssueRequest(PydanticBaseModel):
    state: str | None = None
    labels: list[str] | None = None
    assignee: str | None = None
    title: str | None = None
    body: str | None = None


@app.patch("/api/projects/{owner}/{repo}/issues/{number}")
async def update_project_issue(
    owner: str,
    repo: str,
    number: int,
    req: UpdateIssueRequest,
) -> dict:
    """Update an issue (close, label, assign, etc.)."""
    client = _get_github_http()
    payload: dict = {}
    if req.state is not None:
        payload["state"] = req.state
    if req.labels is not None:
        payload["labels"] = req.labels
    if req.assignee is not None:
        payload["assignees"] = [req.assignee]
    if req.title is not None:
        payload["title"] = req.title
    if req.body is not None:
        payload["body"] = req.body

    resp = await client.patch(f"/repos/{owner}/{repo}/issues/{number}", json=payload)
    resp.raise_for_status()
    return resp.json()


# ---------- Event bus endpoint ----------


class EventPayload(PydanticBaseModel):
    type: str  # e.g. "git_push", "git_commit", "branch_switch", "task_complete"
    workspace: str = ""
    branch: str = ""
    detail: str = ""


# Maps event types to the sensor class names to trigger.
_EVENT_SENSOR_MAP: dict[str, set[str]] = {
    "git_push": {"workspacesensor", "githubsensor"},
    "git_commit": {"workspacesensor"},
    "branch_switch": {"workspacesensor"},
    "task_complete": {"workspacesensor"},
}


@app.post("/api/events")
async def ingest_event(event: EventPayload) -> dict[str, str]:
    """Accept a VS Code event and trigger a targeted pipeline run."""
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not ready")

    sensor_types = _EVENT_SENSOR_MAP.get(event.type)
    if not sensor_types:
        logger.info("Unknown event type %s — running full pipeline", event.type)
        sensor_types = None

    logger.info("Event received: %s (workspace=%s, branch=%s)", event.type, event.workspace, event.branch)
    asyncio.create_task(_pipeline.run_once(sensor_types=sensor_types))
    return {"status": "accepted", "event_type": event.type}


# ---------- Google Calendar OAuth endpoints ----------

_GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.events.readonly"]


@app.post("/api/auth/google")
async def start_google_auth() -> dict[str, str]:
    """Generate a Google OAuth URL.  The extension opens it in the browser."""
    global _pending_oauth_flow

    if not settings.google_client_secret_file:
        raise HTTPException(
            status_code=400,
            detail="Set samwise.google.clientSecretPath in VS Code settings first.",
        )

    secret_path = Path(settings.google_client_secret_file)
    if not secret_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Client secret file not found: {secret_path}",
        )

    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

    flow = InstalledAppFlow.from_client_secrets_file(
        str(secret_path), _GOOGLE_SCOPES
    )
    flow.redirect_uri = f"http://localhost:{_actual_port}/api/auth/google/callback"

    auth_url, _ = flow.authorization_url(
        access_type="offline", prompt="consent"
    )
    _pending_oauth_flow = flow
    return {"auth_url": auth_url}


@app.get("/api/auth/google/callback")
async def google_auth_callback(
    code: str = Query(""),
    error: str = Query(""),
) -> HTMLResponse:
    """OAuth redirect handler — Google sends the user here after consent."""
    global _pending_oauth_flow

    if error:
        _pending_oauth_flow = None
        return HTMLResponse(
            f"<h1>Authentication failed</h1><p>{error}</p>",
            status_code=400,
        )

    if not _pending_oauth_flow:
        return HTMLResponse(
            "<h1>No pending auth flow</h1>"
            "<p>Please start authentication from VS Code again.</p>",
            status_code=400,
        )

    flow = _pending_oauth_flow
    _pending_oauth_flow = None

    try:
        await asyncio.to_thread(flow.fetch_token, code=code)
    except Exception as exc:
        logger.exception("Failed to exchange OAuth code for token")
        return HTMLResponse(
            f"<h1>Token exchange failed</h1><p>{exc}</p>",
            status_code=500,
        )

    creds = flow.credentials
    token_path = settings.data_dir / "google_token.json"
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())

    logger.info("Google Calendar token saved to %s", token_path)
    return HTMLResponse(
        "<html><body style='font-family:system-ui;text-align:center;margin-top:80px'>"
        "<h1>&#10003; Google Calendar Connected</h1>"
        "<p>You can close this tab and return to VS Code.</p>"
        "</body></html>"
    )


@app.get("/api/auth/google/status")
async def google_auth_status() -> dict[str, bool]:
    """Check whether a Google Calendar token file exists."""
    token_path = settings.data_dir / "google_token.json"
    return {"authenticated": token_path.exists()}


def main() -> None:
    global _actual_port

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

    _actual_port = port

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
