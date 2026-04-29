from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from samwise.config import Settings
from samwise.models import ActivityCategory, ActivityItem
from samwise.sensors.base import Sensor

logger = logging.getLogger(__name__)

# Patterns that indicate debug artifacts left in source code.
_DEBUG_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("console.log", re.compile(r"\bconsole\.log\b")),
    ("breakpoint()", re.compile(r"\bbreakpoint\(\)")),
    ("debugger", re.compile(r"\bdebugger\b")),
    ("TODO(hack)", re.compile(r"TODO\s*\(\s*hack\s*\)", re.IGNORECASE)),
]

# File extensions to scan for debug artifacts.
_SCAN_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}


class WorkspaceSensor(Sensor):
    """Monitors local workspace git state and code health."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._roots = [Path(r) for r in settings.workspace_roots]

    async def poll(self) -> list[ActivityItem]:
        if not self._roots:
            return []

        items: list[ActivityItem] = []
        for root in self._roots:
            if not (root / ".git").exists():
                continue
            try:
                root_items = await self._check_workspace(root)
                items.extend(root_items)
            except Exception:
                logger.exception("WorkspaceSensor: error checking %s", root)

        return items

    async def _check_workspace(self, root: Path) -> list[ActivityItem]:
        items: list[ActivityItem] = []
        now = datetime.now(UTC)
        name = root.name

        # Fetch from remote so divergence checks are up-to-date.
        await self._run_git(root, "fetch", "--quiet")

        branch = await self._current_branch(root)
        if not branch:
            return items

        default_branch = await self._default_branch(root)

        # --- Merge conflict early warning ---
        if branch != default_branch:
            divergence = await self._branch_divergence(root, branch, default_branch)
            if divergence:
                behind, conflicts = divergence
                if conflicts > 0:
                    items.append(
                        ActivityItem(
                            id=f"ws-conflict-{name}-{branch}",
                            category=ActivityCategory.CODE_SHIPPING,
                            icon="⚠️",
                            title=f"{name}/{branch}: merge conflicts likely",
                            detail=f"{behind} commits behind {default_branch}, {conflicts} conflicting file(s)",
                            timestamp=now,
                            metadata={
                                "workspace": name,
                                "branch": branch,
                                "sensor_type": "workspace",
                                "conflict_warning": "true",
                                "behind_count": str(behind),
                                "conflict_files": str(conflicts),
                            },
                        )
                    )
                elif behind > 20:
                    items.append(
                        ActivityItem(
                            id=f"ws-divergence-{name}-{branch}",
                            category=ActivityCategory.CODE_SHIPPING,
                            icon="🔀",
                            title=f"{name}/{branch}: drifting from {default_branch}",
                            detail=f"{behind} commits behind — consider rebasing",
                            timestamp=now,
                            metadata={
                                "workspace": name,
                                "branch": branch,
                                "sensor_type": "workspace",
                                "divergence_warning": "true",
                                "behind_count": str(behind),
                            },
                        )
                    )

        # --- Unpushed commits without open PR ---
        unpushed = await self._unpushed_commit_count(root, branch)
        if unpushed > 0 and branch != default_branch:
            items.append(
                ActivityItem(
                    id=f"ws-unpushed-{name}-{branch}",
                    category=ActivityCategory.CODE_SHIPPING,
                    icon="📤",
                    title=f"{name}/{branch}: {unpushed} unpushed commit{'s' if unpushed != 1 else ''}",
                    detail="Push and open a PR when ready",
                    timestamp=now,
                    metadata={
                        "workspace": name,
                        "branch": branch,
                        "sensor_type": "workspace",
                        "unpushed": str(unpushed),
                    },
                )
            )

        # --- Debug artifacts in staged/modified files ---
        debug_items = await self._scan_debug_artifacts(root, name, branch, now)
        items.extend(debug_items)

        # --- Preflight: auto-detect and run lint/test ---
        preflight_items = await self._run_preflight(root, name, branch, now)
        items.extend(preflight_items)

        return items

    # ----- Git helpers -----

    async def _run_git(self, root: Path, *args: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip()

    async def _current_branch(self, root: Path) -> str | None:
        result = await self._run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
        return result if result and result != "HEAD" else None

    async def _default_branch(self, root: Path) -> str:
        # Try to detect from remote HEAD.
        result = await self._run_git(root, "symbolic-ref", "refs/remotes/origin/HEAD")
        if result:
            return result.split("/")[-1]
        return "main"

    async def _branch_divergence(
        self, root: Path, branch: str, default_branch: str,
    ) -> tuple[int, int] | None:
        """Return (commits_behind, conflicting_files) or None if clean."""
        # How many commits is branch behind default?
        behind_str = await self._run_git(
            root, "rev-list", "--count", f"{branch}..origin/{default_branch}",
        )
        try:
            behind = int(behind_str)
        except ValueError:
            return None

        if behind == 0:
            return None

        # Check for potential merge conflicts (dry-run merge).
        merge_base = await self._run_git(root, "merge-base", branch, f"origin/{default_branch}")
        if not merge_base:
            return (behind, 0)

        # Use merge-tree (git >= 2.38) to detect conflicts without touching worktree.
        result = await self._run_git(root, "merge-tree", merge_base, branch, f"origin/{default_branch}")
        # merge-tree outputs conflict markers; count files with "<<<<<<<".
        conflicts = result.count("<" * 7)
        return (behind, conflicts)

    async def _unpushed_commit_count(self, root: Path, branch: str) -> int:
        tracking = await self._run_git(root, "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}")
        if not tracking:
            # No upstream → all commits since divergence from default are "unpushed".
            default = await self._default_branch(root)
            count_str = await self._run_git(root, "rev-list", "--count", f"origin/{default}..{branch}")
        else:
            count_str = await self._run_git(root, "rev-list", "--count", f"{tracking}..{branch}")
        try:
            return int(count_str)
        except ValueError:
            return 0

    # ----- Debug artifact scanning -----

    async def _scan_debug_artifacts(
        self, root: Path, name: str, branch: str, now: datetime,
    ) -> list[ActivityItem]:
        """Scan files changed on this branch for debug artifacts."""
        # Get files changed on this branch vs default.
        default = await self._default_branch(root)
        diff_output = await self._run_git(root, "diff", "--name-only", f"origin/{default}...{branch}")
        if not diff_output:
            return []

        changed_files = [f for f in diff_output.splitlines() if Path(f).suffix in _SCAN_EXTENSIONS]
        if not changed_files:
            return []

        hits: list[str] = []
        for rel_path in changed_files[:50]:  # Cap to avoid scanning too many files.
            file_path = root / rel_path
            if not file_path.is_file():
                continue
            try:
                content = file_path.read_text(errors="ignore")
            except OSError:
                continue
            for label, pattern in _DEBUG_PATTERNS:
                if pattern.search(content):
                    hits.append(f"{rel_path}: {label}")

        if not hits:
            return []

        return [
            ActivityItem(
                id=f"ws-debug-{name}-{branch}",
                category=ActivityCategory.CODE_SHIPPING,
                icon="🧹",
                title=f"{name}/{branch}: {len(hits)} debug artifact{'s' if len(hits) != 1 else ''} found",
                detail=" · ".join(hits[:5]) + (" …" if len(hits) > 5 else ""),
                timestamp=now,
                metadata={
                    "workspace": name,
                    "branch": branch,
                    "sensor_type": "workspace",
                    "debug_artifacts": "true",
                    "hit_count": str(len(hits)),
                },
            )
        ]

    # ----- Preflight auto-detection -----

    async def _run_preflight(
        self, root: Path, name: str, branch: str, now: datetime,
    ) -> list[ActivityItem]:
        """Auto-detect and run lint/test commands; report failures."""
        commands = self._detect_preflight_commands(root)
        if not commands:
            return []

        items: list[ActivityItem] = []
        for label, cmd in commands:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode != 0:
                output = (stderr or stdout).decode(errors="ignore").strip()
                # Truncate to keep the item manageable.
                summary = output[-300:] if len(output) > 300 else output
                items.append(
                    ActivityItem(
                        id=f"ws-preflight-{name}-{branch}-{label}",
                        category=ActivityCategory.CODE_SHIPPING,
                        icon="🚨",
                        title=f"{name}: {label} failed",
                        detail=summary,
                        timestamp=now,
                        metadata={
                            "workspace": name,
                            "branch": branch,
                            "sensor_type": "workspace",
                            "preflight_failure": "true",
                            "check": label,
                        },
                    )
                )

        return items

    @staticmethod
    def _detect_preflight_commands(root: Path) -> list[tuple[str, str]]:
        """Return (label, shell_command) pairs detected from project config."""
        commands: list[tuple[str, str]] = []

        # --- package.json ---
        pkg_json = root / "package.json"
        if pkg_json.is_file():
            try:
                pkg = json.loads(pkg_json.read_text())
                scripts = pkg.get("scripts", {})
                if "lint" in scripts:
                    commands.append(("lint", "npm run lint"))
                if "test" in scripts:
                    commands.append(("test", "npm run test"))
                elif "test:unit" in scripts:
                    commands.append(("test", "npm run test:unit"))
            except (json.JSONDecodeError, OSError):
                pass

        # --- pyproject.toml (look for common tool entries) ---
        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            try:
                content = pyproject.read_text()
                # Detect ruff / flake8 / mypy.
                if "[tool.ruff" in content or "[tool.flake8" in content:
                    commands.append(("lint", "ruff check ."))
                elif "[tool.mypy" in content:
                    commands.append(("type-check", "mypy ."))
                # Detect pytest.
                if "[tool.pytest" in content:
                    commands.append(("test", "pytest"))
            except OSError:
                pass

        return commands

    async def close(self) -> None:
        pass
