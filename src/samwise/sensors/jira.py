from __future__ import annotations

import logging
from base64 import b64encode
from datetime import UTC, datetime
from typing import Any

import httpx

from samwise.config import Settings
from samwise.models import ActivityCategory, ActivityItem
from samwise.sensors.base import Sensor

logger = logging.getLogger(__name__)


class JiraSensor(Sensor):
    """Poll Jira Cloud for sprint-board activity.

    Fetches:
    - Issues assigned to you in the active sprint
    - Issues you're assigned to that were recently updated
    - Blocked / flagged issues in the sprint
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        base = settings.jira_base_url.rstrip("/")
        token = b64encode(
            f"{settings.jira_email}:{settings.jira_api_token}".encode()
        ).decode()
        self._client = httpx.AsyncClient(
            base_url=f"{base}/rest/api/3",
            headers={
                "Authorization": f"Basic {token}",
                "Accept": "application/json",
            },
            timeout=15.0,
        )

    async def poll(self) -> list[ActivityItem]:
        if not self._settings.jira_base_url:
            logger.warning("No Jira base URL configured — skipping Jira sensor")
            return []

        items: list[ActivityItem] = []

        try:
            sprint_items = await self._fetch_my_sprint_issues()
            items.extend(sprint_items)
        except httpx.HTTPError:
            logger.exception("Jira API error during sprint issue fetch")

        try:
            updated_items = await self._fetch_recently_updated()
            items.extend(updated_items)
        except httpx.HTTPError:
            logger.exception("Jira API error during recently-updated fetch")

        return items

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Internal fetches
    # ------------------------------------------------------------------

    async def _fetch_my_sprint_issues(self) -> list[ActivityItem]:
        """Issues assigned to current user in any active sprint."""
        resp = await self._client.post(
            "/search/jql",
            json={
                "jql": "assignee = currentUser() AND sprint in openSprints() ORDER BY priority DESC",
                "maxResults": 30,
                "fields": ["summary", "status", "priority", "updated", "issuetype", "flagged"],
            },
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

        items: list[ActivityItem] = []
        seen_keys: set[str] = set()

        for issue in data.get("issues", []):
            key: str = issue["key"]
            seen_keys.add(key)
            fields = issue.get("fields", {})
            summary: str = fields.get("summary", "")
            status_name: str = fields.get("status", {}).get("name", "Unknown")
            priority_name: str = fields.get("priority", {}).get("name", "Medium")
            updated_str: str = fields.get("updated", "")
            issue_type: str = fields.get("issuetype", {}).get("name", "Task")
            flagged: bool = bool(fields.get("flagged"))

            updated = _parse_jira_datetime(updated_str)
            icon = _icon_for_issue_type(issue_type)

            item = ActivityItem(
                id=f"jira-sprint-{key}",
                category=ActivityCategory.SPRINT,
                icon=icon,
                title=f"{key}: {summary}",
                detail=f"{status_name} · {priority_name}",
                timestamp=updated,
                metadata={"jira_key": key, "status": status_name, "priority": priority_name},
            )
            items.append(item)

            if flagged:
                items.append(
                    ActivityItem(
                        id=f"jira-flagged-{key}",
                        category=ActivityCategory.SPRINT,
                        icon="🚩",
                        title=f"{key} is flagged",
                        detail=f"{summary} — blocked or needs attention",
                        timestamp=updated,
                        metadata={"jira_key": key, "status": status_name},
                    )
                )

        return items

    async def _fetch_recently_updated(self) -> list[ActivityItem]:
        """Issues assigned to user updated in the last poll interval (catch status transitions)."""
        resp = await self._client.post(
            "/search/jql",
            json={
                "jql": (
                    "assignee = currentUser() AND updatedDate >= -15m "
                    "AND status changed DURING (-15m, now()) "
                    "ORDER BY updated DESC"
                ),
                "maxResults": 10,
                "fields": ["summary", "status", "priority", "updated", "issuetype"],
            },
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

        items: list[ActivityItem] = []
        for issue in data.get("issues", []):
            key = issue["key"]
            fields = issue.get("fields", {})
            summary = fields.get("summary", "")
            status_name = fields.get("status", {}).get("name", "Unknown")
            updated_str = fields.get("updated", "")
            updated = _parse_jira_datetime(updated_str)

            items.append(
                ActivityItem(
                    id=f"jira-transition-{key}-{int(updated.timestamp())}",
                    category=ActivityCategory.SPRINT,
                    icon="🔀",
                    title=f"{key} moved to {status_name}",
                    detail=summary,
                    timestamp=updated,
                    metadata={"jira_key": key, "status": status_name},
                )
            )

        return items


def _parse_jira_datetime(s: str) -> datetime:
    """Parse Jira's ISO-8601 datetime (with timezone offset)."""
    if not s:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.now(UTC)


def _icon_for_issue_type(issue_type: str) -> str:
    icons: dict[str, str] = {
        "Bug": "🐛",
        "Story": "📖",
        "Task": "✅",
        "Sub-task": "📌",
        "Epic": "🏔️",
        "Spike": "🔬",
    }
    return icons.get(issue_type, "📋")
