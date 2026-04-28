from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx

from samwise.config import Settings
from samwise.models import ActivityCategory, ActivityItem
from samwise.sensors.base import Sensor

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"


class ProjectSensor(Sensor):
    """Monitors explicitly-configured GitHub repos for staleness and open issues."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=_GITHUB_API,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {settings.github_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15.0,
        )

    async def poll(self) -> list[ActivityItem]:
        if not self._settings.github_token:
            logger.warning("No GitHub token configured — skipping project sensor")
            return []

        repos = self._settings.project_repos
        if not repos:
            return []

        items: list[ActivityItem] = []
        for repo in repos:
            try:
                repo_items = await self._poll_repo(repo)
                items.extend(repo_items)
            except httpx.HTTPError:
                logger.exception("Project sensor: error polling %s", repo)

        return items

    async def _poll_repo(self, repo: str) -> list[ActivityItem]:
        items: list[ActivityItem] = []
        now = datetime.now(UTC)
        threshold = timedelta(days=self._settings.project_staleness_days)

        # --- Repo metadata (staleness) ---
        resp = await self._client.get(f"/repos/{repo}")
        resp.raise_for_status()
        repo_data = resp.json()

        pushed_at_str = repo_data.get("pushed_at")
        if pushed_at_str:
            pushed_at = datetime.fromisoformat(pushed_at_str)
            idle_days = (now - pushed_at).days
            is_stale = (now - pushed_at) > threshold
            pushed_today = idle_days == 0

            if is_stale:
                items.append(
                    ActivityItem(
                        id=f"proj-stale-{repo}",
                        category=ActivityCategory.PROJECT,
                        icon="🧊",
                        title=f"{repo} is stale",
                        detail=f"{idle_days} days since last push",
                        timestamp=pushed_at,
                        metadata={
                            "repo": repo,
                            "idle_days": str(idle_days),
                            "staleness": "stale",
                        },
                    )
                )
        else:
            pushed_today = False

        # --- Open issues ---
        issues_resp = await self._client.get(
            f"/repos/{repo}/issues",
            params={"state": "open", "per_page": "10", "sort": "updated", "direction": "desc"},
        )
        issues_resp.raise_for_status()
        open_issues: list[dict] = [
            i for i in issues_resp.json() if "pull_request" not in i
        ]

        open_count = repo_data.get("open_issues_count", len(open_issues))

        if open_issues:
            # Active-burst mechanic: if pushed today, surface individual issues
            if pushed_today:
                for issue in open_issues[:5]:
                    labels = ", ".join(
                        lbl["name"] for lbl in issue.get("labels", [])
                    )
                    label_suffix = f" [{labels}]" if labels else ""
                    items.append(
                        ActivityItem(
                            id=f"proj-issue-{repo}-{issue['number']}",
                            category=ActivityCategory.PROJECT,
                            icon="📌",
                            title=f"{repo}#{issue['number']}: {issue['title']}",
                            detail=f"Open issue{label_suffix}",
                            timestamp=datetime.fromisoformat(issue["updated_at"]),
                            metadata={
                                "repo": repo,
                                "issue_number": str(issue["number"]),
                                "burst": "true",
                            },
                        )
                    )
            else:
                # Not in a burst — summarise open issues
                top_titles = [f"#{i['number']} {i['title']}" for i in open_issues[:3]]
                items.append(
                    ActivityItem(
                        id=f"proj-issues-{repo}",
                        category=ActivityCategory.PROJECT,
                        icon="📋",
                        title=f"{repo}: {open_count} open issue{'s' if open_count != 1 else ''}",
                        detail=" · ".join(top_titles),
                        timestamp=datetime.fromisoformat(open_issues[0]["updated_at"]),
                        metadata={
                            "repo": repo,
                            "open_count": str(open_count),
                        },
                    )
                )

        # --- Recently closed issues (progress!) ---
        recently = now - timedelta(days=3)
        closed_resp = await self._client.get(
            f"/repos/{repo}/issues",
            params={
                "state": "closed",
                "since": recently.isoformat(),
                "per_page": "5",
                "sort": "updated",
                "direction": "desc",
            },
        )
        closed_resp.raise_for_status()
        closed_issues = [
            i for i in closed_resp.json() if "pull_request" not in i
        ]

        if closed_issues:
            titles = [f"#{i['number']} {i['title']}" for i in closed_issues[:3]]
            items.append(
                ActivityItem(
                    id=f"proj-closed-{repo}",
                    category=ActivityCategory.PROJECT,
                    icon="✅",
                    title=f"{repo}: {len(closed_issues)} issue{'s' if len(closed_issues) != 1 else ''} closed recently",
                    detail=" · ".join(titles),
                    timestamp=datetime.fromisoformat(closed_issues[0]["updated_at"]),
                    metadata={"repo": repo, "progress": "true"},
                )
            )

        return items

    async def close(self) -> None:
        await self._client.aclose()
