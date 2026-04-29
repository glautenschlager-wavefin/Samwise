"""Tests for the WorkspaceSensor — mock git commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from samwise.models import ActivityCategory
from samwise.sensors.workspace import WorkspaceSensor


def _make_settings(**overrides):
    from types import SimpleNamespace

    defaults = {
        "workspace_roots": ["/tmp/test-workspace"],
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture()
def sensor(tmp_path: Path):
    """Create a WorkspaceSensor pointed at a temp dir with a fake .git."""
    (tmp_path / ".git").mkdir()
    settings = _make_settings(workspace_roots=[str(tmp_path)])
    return WorkspaceSensor(settings)


@pytest.mark.asyncio
async def test_no_workspace_roots_returns_empty():
    settings = _make_settings(workspace_roots=[])
    sensor = WorkspaceSensor(settings)
    items = await sensor.poll()
    assert items == []


@pytest.mark.asyncio
async def test_merge_conflict_warning(sensor, tmp_path):
    """Detects when branch has diverged with conflicts."""

    async def fake_git(root, *args):
        cmd = " ".join(args)
        if "fetch" in cmd:
            return ""
        if "rev-parse --abbrev-ref HEAD" in cmd:
            return "feature-branch"
        if "symbolic-ref" in cmd:
            return "refs/remotes/origin/main"
        if "rev-list --count feature-branch..origin/main" in cmd:
            return "25"
        if "merge-base" in cmd:
            return "abc123"
        if "merge-tree" in cmd:
            return "<<<<<<< \n some conflict \n>>>>>>>"
        if "rev-list --count" in cmd:
            return "3"
        if "rev-parse --abbrev-ref feature-branch@" in cmd:
            return "origin/feature-branch"
        if "diff --name-only" in cmd:
            return ""
        return ""

    sensor._run_git = AsyncMock(side_effect=fake_git)

    items = await sensor.poll()

    conflict_items = [i for i in items if i.metadata.get("conflict_warning") == "true"]
    assert len(conflict_items) == 1
    assert "merge conflicts likely" in conflict_items[0].title


@pytest.mark.asyncio
async def test_divergence_warning(sensor, tmp_path):
    """Detects significant branch divergence without actual conflicts."""

    async def fake_git(root, *args):
        cmd = " ".join(args)
        if "fetch" in cmd:
            return ""
        if "rev-parse --abbrev-ref HEAD" in cmd:
            return "feature-branch"
        if "symbolic-ref" in cmd:
            return "refs/remotes/origin/main"
        if "rev-list --count feature-branch..origin/main" in cmd:
            return "30"
        if "merge-base" in cmd:
            return "abc123"
        if "merge-tree" in cmd:
            return ""  # No conflicts
        if "rev-list --count" in cmd:
            return "5"
        if "rev-parse --abbrev-ref feature-branch@" in cmd:
            return "origin/feature-branch"
        if "diff --name-only" in cmd:
            return ""
        return ""

    sensor._run_git = AsyncMock(side_effect=fake_git)

    items = await sensor.poll()

    divergence = [i for i in items if i.metadata.get("divergence_warning") == "true"]
    assert len(divergence) == 1
    assert "drifting" in divergence[0].title


@pytest.mark.asyncio
async def test_unpushed_commits(sensor, tmp_path):
    """Detects unpushed commits on a feature branch."""

    async def fake_git(root, *args):
        cmd = " ".join(args)
        if "fetch" in cmd:
            return ""
        if "rev-parse --abbrev-ref HEAD" in cmd:
            return "feature-branch"
        if "symbolic-ref" in cmd:
            return "refs/remotes/origin/main"
        if "rev-list --count feature-branch..origin/main" in cmd:
            return "0"
        if "rev-parse --abbrev-ref feature-branch@" in cmd:
            return "origin/feature-branch"
        if "rev-list --count origin/feature-branch..feature-branch" in cmd:
            return "4"
        if "diff --name-only" in cmd:
            return ""
        return ""

    sensor._run_git = AsyncMock(side_effect=fake_git)

    items = await sensor.poll()

    unpushed = [i for i in items if i.metadata.get("unpushed")]
    assert len(unpushed) == 1
    assert "4 unpushed commits" in unpushed[0].title


@pytest.mark.asyncio
async def test_debug_artifacts_detected(sensor, tmp_path):
    """Detects debug artifacts in changed files."""
    # Create a file with a debug artifact.
    src = tmp_path / "app.py"
    src.write_text("x = 1\nbreakpoint()\nprint(x)\n")

    async def fake_git(root, *args):
        cmd = " ".join(args)
        if "fetch" in cmd:
            return ""
        if "rev-parse --abbrev-ref HEAD" in cmd:
            return "main"
        if "symbolic-ref" in cmd:
            return "refs/remotes/origin/main"
        if "diff --name-only" in cmd:
            return "app.py"
        return ""

    sensor._run_git = AsyncMock(side_effect=fake_git)

    items = await sensor.poll()

    debug = [i for i in items if i.metadata.get("debug_artifacts") == "true"]
    assert len(debug) == 1
    assert "breakpoint()" in debug[0].detail


@pytest.mark.asyncio
async def test_preflight_detection():
    """Auto-detects lint/test commands from package.json."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        pkg = root / "package.json"
        pkg.write_text('{"scripts": {"lint": "eslint .", "test": "jest"}}')

        commands = WorkspaceSensor._detect_preflight_commands(root)
        labels = [c[0] for c in commands]
        assert "lint" in labels
        assert "test" in labels


@pytest.mark.asyncio
async def test_on_main_branch_skips_divergence(sensor, tmp_path):
    """On the default branch, no divergence or unpushed warnings."""

    async def fake_git(root, *args):
        cmd = " ".join(args)
        if "fetch" in cmd:
            return ""
        if "rev-parse --abbrev-ref HEAD" in cmd:
            return "main"
        if "symbolic-ref" in cmd:
            return "refs/remotes/origin/main"
        if "diff --name-only" in cmd:
            return ""
        return ""

    sensor._run_git = AsyncMock(side_effect=fake_git)

    items = await sensor.poll()

    # Should not have divergence or unpushed warnings
    assert all(i.metadata.get("conflict_warning") != "true" for i in items)
    assert all(i.metadata.get("divergence_warning") != "true" for i in items)
    assert all(not i.metadata.get("unpushed") for i in items)
