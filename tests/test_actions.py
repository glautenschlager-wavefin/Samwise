"""Tests for the action registry and the fix-lint flagship action."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from samwise.config import Settings
from samwise.handlers.actions import (
    FixLintAction,
    MergePRAction,
    build_default_registry,
)
from samwise.handlers.actions.base import SafetyLevel
from samwise.models import ActivityCategory, ActivityItem, Disposition, Urgency


def _item(title: str = "thing", **metadata: str) -> ActivityItem:
    return ActivityItem(
        id="x1",
        category=ActivityCategory.CODE_SHIPPING,
        icon="🔧",
        title=title,
        detail="detail",
        timestamp=datetime.now(tz=UTC),
        urgency=Urgency.HIGH,
        disposition=Disposition.ACT,
        metadata=metadata,
    )


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"github_token": "t", "workspace_roots": []}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Registry routing + safety
# ---------------------------------------------------------------------------


async def test_registry_routes_lint_to_fix_lint() -> None:
    registry = build_default_registry(_settings())
    item = _item(preflight_failure="true", check="lint", workspace="repo")
    try:
        assert isinstance(registry.find(item), FixLintAction)
    finally:
        await registry.close()


async def test_registry_routes_approved_pr_to_merge() -> None:
    registry = build_default_registry(_settings())
    item = _item(title="PR #5 approved", repo="org/repo", pr_number="5")
    try:
        assert isinstance(registry.find(item), MergePRAction)
    finally:
        await registry.close()


async def test_registry_no_match_returns_none() -> None:
    registry = build_default_registry(_settings())
    try:
        assert registry.find(_item(title="nothing actionable")) is None
    finally:
        await registry.close()


async def test_action_safety_levels() -> None:
    assert FixLintAction(_settings()).safety == SafetyLevel.AUTO
    merge = MergePRAction(_settings())
    try:
        assert merge.safety == SafetyLevel.CONFIRM
    finally:
        await merge.close()


# ---------------------------------------------------------------------------
# fix-lint action — real temp git repo
# ---------------------------------------------------------------------------


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _make_repo(tmp_path: Path) -> tuple[Path, str]:
    """Create a clone with a bare origin; return (worktree, default_branch)."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    work = tmp_path / "work"
    subprocess.run(
        ["git", "clone", str(origin), str(work)], check=True, capture_output=True
    )
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    _git(work, "config", "commit.gpgsign", "false")
    (work / "pyproject.toml").write_text('[tool.ruff.lint]\nselect = ["I"]\n')
    (work / "mod.py").write_text("import os\nimport sys\n\nprint(os, sys)\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "init")
    default = _git(work, "rev-parse", "--abbrev-ref", "HEAD")
    _git(work, "push", "origin", default)
    _git(work, "remote", "set-head", "origin", default)
    return work, default


async def test_fix_lint_fixes_commits_and_pushes(tmp_path: Path) -> None:
    work, _ = _make_repo(tmp_path)
    _git(work, "checkout", "-b", "feature-x")
    # Commit an unsorted-import (lint failure) so the worktree is clean.
    (work / "mod.py").write_text("import sys\nimport os\n\nprint(os, sys)\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "wip")

    settings = _settings(workspace_roots=[str(work)], auto_fix_lint=True)
    action = FixLintAction(settings)
    item = _item(preflight_failure="true", check="lint", workspace=work.name, branch="feature-x")

    result = await action.execute(item)

    assert result.disposition == Disposition.NOTIFY
    assert "auto-fixed" in result.title
    assert _git(work, "log", "-1", "--pretty=%s") == "style: auto-fix lint (Samwise)"
    assert (work / "mod.py").read_text().startswith("import os\nimport sys")


async def test_fix_lint_skips_on_default_branch(tmp_path: Path) -> None:
    work, default = _make_repo(tmp_path)
    (work / "mod.py").write_text("import sys\nimport os\n\nprint(os, sys)\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "wip")

    action = FixLintAction(_settings(workspace_roots=[str(work)], auto_fix_lint=True))
    item = _item(preflight_failure="true", check="lint", workspace=work.name, branch=default)

    result = await action.execute(item)

    assert "default branch" in result.detail
    assert _git(work, "log", "-1", "--pretty=%s") == "wip"


async def test_fix_lint_skips_when_worktree_dirty(tmp_path: Path) -> None:
    work, _ = _make_repo(tmp_path)
    _git(work, "checkout", "-b", "feature-x")
    (work / "untracked.py").write_text("x = 1\n")

    action = FixLintAction(_settings(workspace_roots=[str(work)], auto_fix_lint=True))
    item = _item(preflight_failure="true", check="lint", workspace=work.name, branch="feature-x")

    result = await action.execute(item)

    assert "uncommitted" in result.detail


async def test_fix_lint_disabled_notifies() -> None:
    action = FixLintAction(_settings(auto_fix_lint=False))
    item = _item(preflight_failure="true", check="lint", workspace="repo", branch="b")

    result = await action.execute(item)

    assert result.disposition == Disposition.NOTIFY
    assert "Auto-fix is off" in result.detail


async def test_fix_lint_notifies_when_workspace_not_local() -> None:
    action = FixLintAction(_settings(workspace_roots=[], auto_fix_lint=True))
    item = _item(preflight_failure="true", check="lint", workspace="ghost", branch="b")

    result = await action.execute(item)

    assert "can't auto-fix" in result.title
