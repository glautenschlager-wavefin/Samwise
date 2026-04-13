from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from samwise.config import Settings
from samwise.models import ActivityCategory, ActivityItem
from samwise.sensors.base import Sensor

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"


class GitHubSensor(Sensor):
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
            logger.warning("No GitHub token configured — skipping GitHub sensor")
            return []

        items: list[ActivityItem] = []
        username = self._settings.github_username

        try:
            my_prs = await self._fetch_my_prs(username)
            items.extend(my_prs)

            review_requests = await self._fetch_review_requests(username)
            items.extend(review_requests)

            notifications = await self._fetch_notifications()
            items.extend(notifications)
        except httpx.HTTPError:
            logger.exception("GitHub API error during poll")

        return items

    async def _fetch_my_prs(self, username: str) -> list[ActivityItem]:
        """Fetch PRs authored by the user and their CI/review status."""
        resp = await self._client.get(
            "/search/issues",
            params={
                "q": f"type:pr state:open author:{username}",
                "sort": "updated",
                "per_page": "20",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        items: list[ActivityItem] = []
        for pr in data.get("items", []):
            pr_number = pr["number"]
            repo_full = pr["repository_url"].removeprefix(f"{_GITHUB_API}/repos/")
            title = pr["title"]
            updated = datetime.fromisoformat(pr["updated_at"])

            # Check for approvals and review comments via labels/reactions heuristic
            # or the PR review endpoint
            reviews = await self._fetch_pr_reviews(repo_full, pr_number)
            approved = any(r["state"] == "APPROVED" for r in reviews)
            has_comments = any(r["state"] == "CHANGES_REQUESTED" for r in reviews)

            if approved:
                items.append(
                    ActivityItem(
                        id=f"gh-pr-approved-{repo_full}-{pr_number}",
                        category=ActivityCategory.CODE_SHIPPING,
                        icon="👀",
                        title=f"PR #{pr_number} approved",
                        detail=f"{repo_full}: {title} — ready to merge",
                        timestamp=updated,
                        metadata={"repo": repo_full, "pr_number": str(pr_number)},
                    )
                )
            elif has_comments:
                items.append(
                    ActivityItem(
                        id=f"gh-pr-changes-{repo_full}-{pr_number}",
                        category=ActivityCategory.CODE_SHIPPING,
                        icon="💬",
                        title=f"PR #{pr_number} needs changes",
                        detail=f"{repo_full}: {title} — changes requested",
                        timestamp=updated,
                        metadata={"repo": repo_full, "pr_number": str(pr_number)},
                    )
                )
            else:
                items.append(
                    ActivityItem(
                        id=f"gh-pr-open-{repo_full}-{pr_number}",
                        category=ActivityCategory.CODE_SHIPPING,
                        icon="🔄",
                        title=f"PR #{pr_number} open",
                        detail=f"{repo_full}: {title}",
                        timestamp=updated,
                        metadata={"repo": repo_full, "pr_number": str(pr_number)},
                    )
                )

            # Check CI status
            checks = await self._fetch_check_status(repo_full, pr.get("pull_request", {}).get("url", ""), pr_number)
            if checks == "failure":
                items.append(
                    ActivityItem(
                        id=f"gh-ci-fail-{repo_full}-{pr_number}",
                        category=ActivityCategory.CODE_SHIPPING,
                        icon="🔴",
                        title=f"CI failing on PR #{pr_number}",
                        detail=f"{repo_full}: {title}",
                        timestamp=updated,
                        metadata={"repo": repo_full, "pr_number": str(pr_number)},
                    )
                )

        return items

    async def _fetch_pr_reviews(self, repo: str, pr_number: int) -> list[dict[str, str]]:
        try:
            resp = await self._client.get(f"/repos/{repo}/pulls/{pr_number}/reviews")
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except httpx.HTTPError:
            logger.warning("Failed to fetch reviews for %s #%d", repo, pr_number)
            return []

    async def _fetch_check_status(self, repo: str, _pr_url: str, pr_number: int) -> str | None:
        """Return 'success', 'failure', 'pending', or None."""
        try:
            resp = await self._client.get(
                f"/repos/{repo}/pulls/{pr_number}",
            )
            resp.raise_for_status()
            pr_data = resp.json()
            head_sha = pr_data.get("head", {}).get("sha")
            if not head_sha:
                return None

            status_resp = await self._client.get(f"/repos/{repo}/commits/{head_sha}/status")
            status_resp.raise_for_status()
            return status_resp.json().get("state")  # type: ignore[no-any-return]
        except httpx.HTTPError:
            logger.warning("Failed to fetch CI status for %s #%d", repo, pr_number)
            return None

    async def _fetch_review_requests(self, username: str) -> list[ActivityItem]:
        """Fetch PRs where the user's review is requested."""
        resp = await self._client.get(
            "/search/issues",
            params={
                "q": f"type:pr state:open review-requested:{username}",
                "sort": "updated",
                "per_page": "10",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        items: list[ActivityItem] = []
        for pr in data.get("items", []):
            pr_number = pr["number"]
            repo_full = pr["repository_url"].removeprefix(f"{_GITHUB_API}/repos/")
            title = pr["title"]
            user = pr.get("user", {}).get("login", "someone")
            updated = datetime.fromisoformat(pr["updated_at"])

            items.append(
                ActivityItem(
                    id=f"gh-review-req-{repo_full}-{pr_number}",
                    category=ActivityCategory.CODE_SHIPPING,
                    icon="🔔",
                    title=f"Review requested on #{pr_number}",
                    detail=f"@{user} wants your review — {repo_full}: {title}",
                    timestamp=updated,
                )
            )

        return items

    async def _fetch_notifications(self) -> list[ActivityItem]:
        """Fetch recent unread GitHub notifications."""
        try:
            resp = await self._client.get(
                "/notifications",
                params={"per_page": "10", "all": "false"},
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.warning("Failed to fetch notifications")
            return []

        items: list[ActivityItem] = []
        for notif in resp.json():
            reason = notif.get("reason", "")
            subject = notif.get("subject", {})
            title = subject.get("title", "")
            repo = notif.get("repository", {}).get("full_name", "")
            updated = datetime.fromisoformat(notif["updated_at"])

            # Skip reasons already covered by PR queries
            if reason in ("review_requested", "author"):
                continue

            icon = "🔔"
            if reason == "mention":
                icon = "💬"
            elif reason == "ci_activity":
                icon = "🔴"

            items.append(
                ActivityItem(
                    id=f"gh-notif-{notif['id']}",
                    category=ActivityCategory.CODE_SHIPPING,
                    icon=icon,
                    title=title,
                    detail=f"{repo} — {reason}",
                    timestamp=updated,
                )
            )

        return items

    async def close(self) -> None:
        await self._client.aclose()
