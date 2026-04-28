"""Tests for the ProjectSensor — mock GitHub API responses."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from samwise.models import ActivityCategory, Urgency
from samwise.sensors.project import ProjectSensor


def _make_settings(**overrides):
    """Create a minimal Settings-like object for testing."""
    from types import SimpleNamespace

    defaults = {
        "github_token": "ghp_test",
        "github_username": "testuser",
        "project_repos": ["owner/repo"],
        "project_staleness_days": 5,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _repo_json(pushed_at: datetime, open_issues_count: int = 3) -> dict:
    return {
        "pushed_at": pushed_at.isoformat(),
        "open_issues_count": open_issues_count,
    }


def _issue_json(number: int, title: str, state: str = "open", labels=None, updated_at=None) -> dict:
    return {
        "number": number,
        "title": title,
        "state": state,
        "labels": [{"name": l} for l in (labels or [])],
        "updated_at": (updated_at or datetime.now(UTC)).isoformat(),
    }


class _FakeResponse:
    """Minimal httpx.Response stand-in."""

    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


@pytest.mark.asyncio
async def test_stale_repo_produces_high_urgency_item():
    """A repo with no push beyond the threshold generates a stale item."""
    now = datetime.now(UTC)
    stale_push = now - timedelta(days=10)

    settings = _make_settings()
    sensor = ProjectSensor(settings)

    async def fake_get(url, **kwargs):
        if url == "/repos/owner/repo":
            return _FakeResponse(_repo_json(stale_push))
        if "state" in kwargs.get("params", {}) and kwargs["params"]["state"] == "open":
            return _FakeResponse([])
        # closed issues
        return _FakeResponse([])

    sensor._client = AsyncMock()
    sensor._client.get = AsyncMock(side_effect=fake_get)

    items = await sensor.poll()

    stale_items = [i for i in items if "stale" in i.title.lower()]
    assert len(stale_items) == 1
    assert stale_items[0].category == ActivityCategory.PROJECT
    assert stale_items[0].metadata["staleness"] == "stale"
    assert int(stale_items[0].metadata["idle_days"]) >= 10


@pytest.mark.asyncio
async def test_active_burst_surfaces_individual_issues():
    """When a repo was pushed today, individual issues appear with burst=true."""
    now = datetime.now(UTC)
    pushed_today = now - timedelta(hours=2)

    settings = _make_settings()
    sensor = ProjectSensor(settings)

    open_issues = [
        _issue_json(1, "Add feature X", updated_at=now),
        _issue_json(2, "Fix bug Y", updated_at=now - timedelta(hours=1)),
    ]

    async def fake_get(url, **kwargs):
        if url == "/repos/owner/repo":
            return _FakeResponse(_repo_json(pushed_today))
        params = kwargs.get("params", {})
        if params.get("state") == "open":
            return _FakeResponse(open_issues)
        # closed issues
        return _FakeResponse([])

    sensor._client = AsyncMock()
    sensor._client.get = AsyncMock(side_effect=fake_get)

    items = await sensor.poll()

    burst_items = [i for i in items if i.metadata.get("burst") == "true"]
    assert len(burst_items) == 2
    assert all(i.category == ActivityCategory.PROJECT for i in burst_items)
    assert all(i.icon == "📌" for i in burst_items)


@pytest.mark.asyncio
async def test_no_repos_configured_returns_empty():
    settings = _make_settings(project_repos=[])
    sensor = ProjectSensor(settings)
    items = await sensor.poll()
    assert items == []


@pytest.mark.asyncio
async def test_no_token_returns_empty():
    settings = _make_settings(github_token="")
    sensor = ProjectSensor(settings)
    items = await sensor.poll()
    assert items == []


@pytest.mark.asyncio
async def test_issues_summary_when_not_in_burst():
    """When repo is NOT pushed today, shows summary of open issues instead of individual ones."""
    now = datetime.now(UTC)
    pushed_2_days_ago = now - timedelta(days=2)

    settings = _make_settings()
    sensor = ProjectSensor(settings)

    open_issues = [
        _issue_json(1, "Add feature X", updated_at=now),
        _issue_json(2, "Fix bug Y", updated_at=now - timedelta(hours=1)),
    ]

    async def fake_get(url, **kwargs):
        if url == "/repos/owner/repo":
            return _FakeResponse(_repo_json(pushed_2_days_ago, open_issues_count=2))
        params = kwargs.get("params", {})
        if params.get("state") == "open":
            return _FakeResponse(open_issues)
        return _FakeResponse([])

    sensor._client = AsyncMock()
    sensor._client.get = AsyncMock(side_effect=fake_get)

    items = await sensor.poll()

    summary_items = [i for i in items if i.metadata.get("open_count")]
    assert len(summary_items) == 1
    assert "2 open issues" in summary_items[0].title
    # Should NOT have individual burst items
    burst_items = [i for i in items if i.metadata.get("burst")]
    assert len(burst_items) == 0
