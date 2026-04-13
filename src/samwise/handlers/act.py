from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from samwise.config import Settings
from samwise.handlers.notify import NotifyHandler
from samwise.models import ActivityCategory, ActivityItem, Urgency

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"


class ActHandler:
    """Execute autonomous actions (e.g. merge approved PRs).

    Results are pushed back through the notify handler so the user
    sees what Samwise did on their behalf.
    """

    def __init__(self, settings: Settings, notify: NotifyHandler) -> None:
        self._settings = settings
        self._notify = notify
        self._client = httpx.AsyncClient(
            base_url=_GITHUB_API,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {settings.github_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15.0,
        )

    async def handle(self, items: list[ActivityItem]) -> None:
        for item in items:
            result = await self._execute(item)
            await self._notify.handle([result])

    async def close(self) -> None:
        await self._client.aclose()

    async def _execute(self, item: ActivityItem) -> ActivityItem:
        repo = item.metadata.get("repo")
        pr_number = item.metadata.get("pr_number")

        if "approved" in item.title.lower() and repo and pr_number:
            return await self._merge_pr(item, repo, int(pr_number))

        logger.info("No automated action for: %s", item.title)
        return ActivityItem(
            id=f"act-skip-{item.id}",
            category=item.category,
            icon="⏭️",
            title=f"Skipped: {item.title}",
            detail="No automated action available for this item type",
            timestamp=datetime.now(UTC),
        )

    async def _merge_pr(self, item: ActivityItem, repo: str, pr_number: int) -> ActivityItem:
        """Merge an approved PR if auto_merge is enabled and CI is green."""
        now = datetime.now(UTC)

        if not self._settings.auto_merge:
            logger.info("Auto-merge disabled — notifying instead: %s #%d", repo, pr_number)
            return ActivityItem(
                id=f"act-would-merge-{repo}-{pr_number}",
                category=ActivityCategory.CODE_SHIPPING,
                icon="ℹ️",
                title=f"PR #{pr_number} ready to merge",
                detail=f"{repo}: approved and ready. Enable SAMWISE_AUTO_MERGE=true to auto-merge.",
                timestamp=now,
                urgency=Urgency.HIGH,
                metadata={"repo": repo, "pr_number": str(pr_number)},
            )

        # Check CI status before merging
        ci_ok = await self._check_ci(repo, pr_number)
        if not ci_ok:
            logger.info("CI not green — skipping merge for %s #%d", repo, pr_number)
            return ActivityItem(
                id=f"act-ci-blocked-{repo}-{pr_number}",
                category=ActivityCategory.CODE_SHIPPING,
                icon="⏳",
                title=f"PR #{pr_number} merge blocked",
                detail=f"{repo}: approved but CI is not passing yet",
                timestamp=now,
                urgency=Urgency.NORMAL,
                metadata={"repo": repo, "pr_number": str(pr_number)},
            )

        # Perform the merge
        try:
            resp = await self._client.put(
                f"/repos/{repo}/pulls/{pr_number}/merge",
                json={"merge_method": "squash"},
            )
            resp.raise_for_status()
            logger.info("Merged PR %s #%d", repo, pr_number)
            return ActivityItem(
                id=f"act-merged-{repo}-{pr_number}",
                category=ActivityCategory.CODE_SHIPPING,
                icon="✅",
                title=f"Merged PR #{pr_number}",
                detail=f"{repo}: squash-merged by Samwise",
                timestamp=now,
                urgency=Urgency.HIGH,
                metadata={"repo": repo, "pr_number": str(pr_number)},
            )
        except httpx.HTTPStatusError as exc:
            logger.error("Failed to merge %s #%d: %s", repo, pr_number, exc.response.text)
            return ActivityItem(
                id=f"act-merge-failed-{repo}-{pr_number}",
                category=ActivityCategory.CODE_SHIPPING,
                icon="❌",
                title=f"Failed to merge PR #{pr_number}",
                detail=f"{repo}: {exc.response.status_code} — {exc.response.text[:200]}",
                timestamp=now,
                urgency=Urgency.HIGH,
                metadata={"repo": repo, "pr_number": str(pr_number)},
            )

    async def _check_ci(self, repo: str, pr_number: int) -> bool:
        """Return True if CI status on the PR head is 'success'."""
        try:
            pr_resp = await self._client.get(f"/repos/{repo}/pulls/{pr_number}")
            pr_resp.raise_for_status()
            head_sha = pr_resp.json().get("head", {}).get("sha")
            if not head_sha:
                return False

            status_resp = await self._client.get(f"/repos/{repo}/commits/{head_sha}/status")
            status_resp.raise_for_status()
            state: str | None = status_resp.json().get("state")
            return state == "success"
        except httpx.HTTPError:
            logger.warning("Failed to check CI for %s #%d", repo, pr_number)
            return False
