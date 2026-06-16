from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from samwise.config import Settings
from samwise.handlers.actions.base import Action, SafetyLevel
from samwise.models import ActivityCategory, ActivityItem, Disposition, Urgency

logger = logging.getLogger(__name__)

_COMMIT_MESSAGE = "style: auto-fix lint (Samwise)"
_CMD_TIMEOUT = 180


class FixLintAction(Action):
    """Auto-fix lint failures on a PR branch and push the result.

    AUTO-level: runs without confirmation when ``settings.auto_fix_lint``
    is enabled (the default). It only operates on a non-default branch with
    a clean working tree, and reverts its own changes if it cannot make lint
    pass — so it never leaves the branch in a worse state.
    """

    name = "fix-lint"
    safety = SafetyLevel.AUTO

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._roots = {Path(r).name: Path(r) for r in settings.workspace_roots}

    def matches(self, item: ActivityItem) -> bool:
        return (
            item.metadata.get("preflight_failure") == "true"
            and item.metadata.get("check") == "lint"
            and bool(item.metadata.get("workspace"))
        )

    async def execute(self, item: ActivityItem) -> ActivityItem:
        now = datetime.now(UTC)
        workspace = item.metadata.get("workspace", "")

        if not self._settings.auto_fix_lint:
            return self._notify(
                item, now, "ℹ️", f"{workspace}: lint failing",
                "Auto-fix is off. Enable SAMWISE_AUTO_FIX_LINT to let Samwise fix it.",
                Urgency.NORMAL, Disposition.NOTIFY,
            )

        root = self._roots.get(workspace)
        if root is None or not (root / ".git").exists():
            return self._notify(
                item, now, "⚠️", f"{workspace}: can't auto-fix lint",
                "Workspace not found locally — fix and push manually.",
                Urgency.NORMAL, Disposition.NOTIFY,
            )

        # Guard: never auto-commit on the default branch.
        default_branch = await self._default_branch(root)
        current = await self._current_branch(root)
        if not current or current == default_branch:
            return self._notify(
                item, now, "⚠️", f"{workspace}: lint failing on {current or 'detached HEAD'}",
                "Won't auto-fix on the default branch — switch to a feature branch.",
                Urgency.NORMAL, Disposition.NOTIFY,
            )

        # Guard: don't clobber unrelated uncommitted work.
        if await self._is_dirty(root):
            return self._notify(
                item, now, "⚠️", f"{workspace}: lint failing (uncommitted changes)",
                "You have uncommitted changes — commit or stash them, then Samwise can auto-fix.",
                Urgency.NORMAL, Disposition.NOTIFY,
            )

        fixer = self._detect_fixer(root)
        if fixer is None:
            return self._notify(
                item, now, "⚠️", f"{workspace}: no lint auto-fixer detected",
                "Couldn't find a supported formatter/linter to run.",
                Urgency.NORMAL, Disposition.NOTIFY,
            )

        # Run the fixer(s).
        for cmd in fixer:
            await self._run_shell(root, cmd)

        if not await self._is_dirty(root):
            return self._notify(
                item, now, "🙋", f"{workspace}: lint needs you",
                "Auto-fixer made no changes — these failures need a manual fix.",
                Urgency.HIGH, Disposition.NOTIFY,
            )

        # Verify lint now passes; revert if not.
        if not await self._lint_passes(root):
            await self._run_git(root, "checkout", "--", ".")
            return self._notify(
                item, now, "🙋", f"{workspace}: lint partially fixable",
                "Samwise reverted its changes — remaining lint errors need you.",
                Urgency.HIGH, Disposition.NOTIFY,
            )

        # Commit and push.
        await self._run_git(root, "add", "-A")
        await self._run_git(root, "commit", "-m", _COMMIT_MESSAGE)
        push_ok = await self._push(root, current)

        if not push_ok:
            return self._notify(
                item, now, "⚠️", f"{workspace}: lint fixed but push failed",
                f"Committed the fix locally on {current}; push it manually.",
                Urgency.HIGH, Disposition.NOTIFY,
            )

        return self._notify(
            item, now, "✅", f"{workspace}: lint auto-fixed",
            f"Fixed and pushed to {current} — the PR will re-run CI.",
            Urgency.NORMAL, Disposition.NOTIFY,
        )

    # ----- result helper -----

    def _notify(
        self,
        item: ActivityItem,
        now: datetime,
        icon: str,
        title: str,
        detail: str,
        urgency: Urgency,
        disposition: Disposition,
    ) -> ActivityItem:
        return ActivityItem(
            id=f"act-fixlint-{item.id}",
            category=ActivityCategory.CODE_SHIPPING,
            icon=icon,
            title=title,
            detail=detail,
            timestamp=now,
            urgency=urgency,
            disposition=disposition,
            metadata={k: v for k, v in item.metadata.items() if k in {"workspace", "branch"}},
        )

    # ----- fixer detection -----

    @staticmethod
    def _detect_fixer(root: Path) -> list[str] | None:
        """Return the shell command(s) that auto-fix lint, or None."""
        pkg_json = root / "package.json"
        if pkg_json.is_file():
            try:
                scripts = json.loads(pkg_json.read_text()).get("scripts", {})
                if "lint" in scripts:
                    return ["npm run lint -- --fix"]
            except (json.JSONDecodeError, OSError):
                pass

        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            try:
                content = pyproject.read_text()
                if "[tool.ruff" in content:
                    return ["ruff check --fix .", "ruff format ."]
            except OSError:
                pass

        return None

    @staticmethod
    def _lint_cmd(root: Path) -> str | None:
        pkg_json = root / "package.json"
        if pkg_json.is_file():
            try:
                scripts = json.loads(pkg_json.read_text()).get("scripts", {})
                if "lint" in scripts:
                    return "npm run lint"
            except (json.JSONDecodeError, OSError):
                pass

        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            try:
                if "[tool.ruff" in pyproject.read_text():
                    return "ruff check ."
            except OSError:
                pass

        return None

    async def _lint_passes(self, root: Path) -> bool:
        cmd = self._lint_cmd(root)
        if cmd is None:
            return True
        code, _ = await self._run_shell(root, cmd)
        return code == 0

    # ----- git helpers -----

    async def _run_git(self, root: Path, *args: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip()

    async def _run_shell(self, root: Path, cmd: str) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_CMD_TIMEOUT)
        except TimeoutError:
            proc.kill()
            return 1, "timed out"
        return proc.returncode or 0, (stderr or stdout).decode(errors="ignore")

    async def _current_branch(self, root: Path) -> str | None:
        result = await self._run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
        return result if result and result != "HEAD" else None

    async def _default_branch(self, root: Path) -> str:
        result = await self._run_git(root, "symbolic-ref", "refs/remotes/origin/HEAD")
        if result:
            return result.split("/")[-1]
        return "main"

    async def _is_dirty(self, root: Path) -> bool:
        return bool(await self._run_git(root, "status", "--porcelain"))

    async def _push(self, root: Path, branch: str) -> bool:
        proc = await asyncio.create_subprocess_exec(
            "git", "push", "origin", branch,
            cwd=root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode == 0
