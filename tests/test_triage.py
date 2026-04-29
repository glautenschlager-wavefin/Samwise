from datetime import UTC, datetime

from samwise.models import ActivityCategory, ActivityItem, Disposition, Urgency
from samwise.triage import triage


def _make_item(**overrides: object) -> ActivityItem:
    defaults = {
        "id": "test-1",
        "category": ActivityCategory.CODE_SHIPPING,
        "icon": "🔄",
        "title": "Test item",
        "detail": "Test detail",
        "timestamp": datetime.now(tz=UTC),
        "urgency": Urgency.NORMAL,
        "disposition": Disposition.NOTIFY,
    }
    defaults.update(overrides)
    return ActivityItem(**defaults)  # type: ignore[arg-type]


def test_ci_failure_becomes_high_urgency() -> None:
    item = _make_item(title="CI failing on PR #42", icon="🔴")
    [result] = triage([item])
    assert result.urgency == Urgency.HIGH
    assert result.disposition == Disposition.NOTIFY


def test_pr_approved_becomes_high_urgency() -> None:
    item = _make_item(title="PR #85 approved", icon="👀")
    [result] = triage([item])
    assert result.urgency == Urgency.HIGH
    assert result.disposition == Disposition.ACT


def test_open_pr_no_action_is_deferred() -> None:
    item = _make_item(title="PR #99 open", icon="🔄")
    [result] = triage([item])
    assert result.urgency == Urgency.LOW
    assert result.disposition == Disposition.DEFER


def test_changes_requested_is_high() -> None:
    item = _make_item(title="PR #50 needs changes", detail="changes requested by @reviewer")
    [result] = triage([item])
    assert result.urgency == Urgency.HIGH


def test_mention_notification_is_high() -> None:
    item = _make_item(title="Discussion on issue", detail="repo — mention", icon="💬")
    [result] = triage([item])
    assert result.urgency == Urgency.HIGH


def test_normal_item_passes_through() -> None:
    item = _make_item(title="Something routine", detail="nothing special")
    [result] = triage([item])
    assert result.urgency == Urgency.NORMAL
    assert result.disposition == Disposition.NOTIFY


def test_triage_preserves_all_items() -> None:
    items = [
        _make_item(id="a", title="CI failing on PR #1", icon="🔴"),
        _make_item(id="b", title="PR #2 open", icon="🔄"),
        _make_item(id="c", title="PR #3 approved"),
    ]
    results = triage(items)
    assert len(results) == 3
    assert {r.id for r in results} == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# Sprint / Jira triage rules
# ---------------------------------------------------------------------------


def _make_sprint_item(**overrides: object) -> ActivityItem:
    defaults = {
        "id": "jira-1",
        "category": ActivityCategory.SPRINT,
        "icon": "✅",
        "title": "PR-100: Some task",
        "detail": "In Progress · Medium",
        "timestamp": datetime.now(tz=UTC),
        "urgency": Urgency.NORMAL,
        "disposition": Disposition.NOTIFY,
        "metadata": {"jira_key": "PR-100", "status": "In Progress", "priority": "Medium"},
    }
    defaults.update(overrides)
    return ActivityItem(**defaults)  # type: ignore[arg-type]


def test_flagged_issue_is_high_urgency() -> None:
    item = _make_sprint_item(title="PR-100 is flagged", icon="🚩")
    [result] = triage([item])
    assert result.urgency == Urgency.HIGH


def test_highest_priority_is_high_urgency() -> None:
    item = _make_sprint_item(
        metadata={"jira_key": "PR-100", "status": "In Progress", "priority": "Highest"},
    )
    [result] = triage([item])
    assert result.urgency == Urgency.HIGH


def test_status_transition_is_normal_notify() -> None:
    item = _make_sprint_item(title="PR-100 moved to Done", icon="🔀")
    [result] = triage([item])
    assert result.urgency == Urgency.NORMAL
    assert result.disposition == Disposition.NOTIFY


def test_low_priority_sprint_is_low_urgency() -> None:
    item = _make_sprint_item(
        metadata={"jira_key": "PR-200", "status": "To Do", "priority": "Low"},
    )
    [result] = triage([item])
    assert result.urgency == Urgency.LOW


# --- Calendar rules ---


def _make_calendar_item(**overrides: object) -> ActivityItem:
    defaults = {
        "id": "gcal-1",
        "category": ActivityCategory.CALENDAR,
        "icon": "📅",
        "title": "Team Standup (in 25 min)",
        "detail": "2:00 PM – 2:30 PM · 5 attendees",
        "timestamp": datetime.now(tz=UTC),
        "urgency": Urgency.NORMAL,
        "disposition": Disposition.NOTIFY,
        "metadata": {"event_id": "abc123", "minutes_until": "25", "attendees": "5"},
    }
    defaults.update(overrides)
    return ActivityItem(**defaults)  # type: ignore[arg-type]


def test_meeting_imminent_is_high_urgency() -> None:
    item = _make_calendar_item(
        title="Team Standup (in 3 min)",
        metadata={"event_id": "abc", "minutes_until": "3", "attendees": "5"},
    )
    [result] = triage([item])
    assert result.urgency == Urgency.HIGH


def test_distant_meeting_is_deferred() -> None:
    item = _make_calendar_item(
        title="Sprint Review (in 90 min)",
        metadata={"event_id": "abc", "minutes_until": "90", "attendees": "10"},
    )
    [result] = triage([item])
    assert result.urgency == Urgency.LOW
    assert result.disposition == Disposition.DEFER


# ---------------------------------------------------------------------------
# Project triage rules
# ---------------------------------------------------------------------------


def _make_project_item(**overrides: object) -> ActivityItem:
    defaults = {
        "id": "proj-1",
        "category": ActivityCategory.PROJECT,
        "icon": "🧊",
        "title": "owner/repo is stale",
        "detail": "7 days since last push",
        "timestamp": datetime.now(tz=UTC),
        "urgency": Urgency.NORMAL,
        "disposition": Disposition.NOTIFY,
        "metadata": {"repo": "owner/repo"},
    }
    defaults.update(overrides)
    return ActivityItem(**defaults)  # type: ignore[arg-type]


def test_stale_project_is_high_urgency() -> None:
    item = _make_project_item(
        metadata={"repo": "owner/repo", "idle_days": "7", "staleness": "stale"},
    )
    [result] = triage([item])
    assert result.urgency == Urgency.HIGH
    assert result.disposition == Disposition.NOTIFY


def test_active_burst_issue_is_normal() -> None:
    item = _make_project_item(
        id="proj-issue-owner/repo-1",
        icon="📌",
        title="owner/repo#1: Add feature",
        detail="Open issue",
        metadata={"repo": "owner/repo", "issue_number": "1", "burst": "true"},
    )
    [result] = triage([item])
    assert result.urgency == Urgency.NORMAL
    assert result.disposition == Disposition.NOTIFY


def test_project_issues_summary_is_deferred() -> None:
    item = _make_project_item(
        id="proj-issues-owner/repo",
        icon="📋",
        title="owner/repo: 5 open issues",
        detail="#1 Feature · #2 Bug · #3 Task",
        metadata={"repo": "owner/repo", "open_count": "5"},
    )
    [result] = triage([item])
    assert result.urgency == Urgency.LOW
    assert result.disposition == Disposition.DEFER


def test_project_progress_is_deferred() -> None:
    item = _make_project_item(
        id="proj-closed-owner/repo",
        icon="✅",
        title="owner/repo: 2 issues closed recently",
        detail="#4 Fix · #5 Cleanup",
        metadata={"repo": "owner/repo", "progress": "true"},
    )
    [result] = triage([item])
    assert result.urgency == Urgency.LOW
    assert result.disposition == Disposition.DEFER


def test_stale_pr_is_high_notify() -> None:
    item = _make_project_item(
        id="proj-pr-stale-owner/repo-42",
        icon="🕸️",
        title="owner/repo#42: WIP feature",
        detail="PR idle for 10 days",
        metadata={"repo": "owner/repo", "pr_number": "42", "pr_stale": "true", "draft": "false", "idle_days": "10"},
    )
    [result] = triage([item])
    assert result.urgency == Urgency.HIGH
    assert result.disposition == Disposition.NOTIFY


# ---------------------------------------------------------------------------
# PR SLA triage rules
# ---------------------------------------------------------------------------


def test_sla_pr_too_large_is_high() -> None:
    item = _make_item(
        id="sla-size-repo-42",
        icon="📏",
        title="owner/repo#42 is too large (800 lines)",
        detail="SLA violation: 800 lines changed vs 600 max",
        metadata={"sla_violation": "size", "pr_number": "42"},
    )
    [result] = triage([item])
    assert result.urgency == Urgency.HIGH
    assert result.disposition == Disposition.NOTIFY


def test_sla_pr_aging_is_high() -> None:
    item = _make_item(
        id="sla-age-repo-42",
        icon="⏳",
        title="owner/repo#42 open for 10 days",
        detail="SLA violation: open 10 days vs 7 day limit",
        metadata={"sla_violation": "age", "pr_number": "42"},
    )
    [result] = triage([item])
    assert result.urgency == Urgency.HIGH
    assert result.disposition == Disposition.NOTIFY


def test_sla_pr_needs_review_is_normal() -> None:
    item = _make_item(
        id="sla-review-repo-42",
        icon="👁️",
        title="owner/repo#42 has 3 pushes without review",
        detail="SLA violation: 3 commits without review vs 2 max",
        metadata={"sla_violation": "review_wait", "pr_number": "42"},
    )
    [result] = triage([item])
    assert result.urgency == Urgency.NORMAL
    assert result.disposition == Disposition.NOTIFY


# ---------------------------------------------------------------------------
# Workspace triage rules
# ---------------------------------------------------------------------------


def test_workspace_conflict_warning_is_high() -> None:
    item = _make_item(
        id="ws-conflict-repo",
        icon="⚠️",
        title="feature-branch → main: merge conflicts likely",
        detail="25 commits behind, conflicts in 3 files",
        metadata={"sensor_type": "workspace", "conflict_warning": "true"},
    )
    [result] = triage([item])
    assert result.urgency == Urgency.HIGH
    assert result.disposition == Disposition.NOTIFY


def test_workspace_divergence_is_normal() -> None:
    item = _make_item(
        id="ws-drift-repo",
        icon="🔀",
        title="feature-branch is drifting from main",
        detail="30 commits behind",
        metadata={"sensor_type": "workspace", "divergence_warning": "true"},
    )
    [result] = triage([item])
    assert result.urgency == Urgency.NORMAL
    assert result.disposition == Disposition.NOTIFY


def test_workspace_unpushed_is_low() -> None:
    item = _make_item(
        id="ws-unpushed-repo",
        icon="📤",
        title="4 unpushed commits on feature-branch",
        detail="Local changes not yet on remote",
        metadata={"sensor_type": "workspace", "unpushed": "4"},
    )
    [result] = triage([item])
    assert result.urgency == Urgency.LOW
    assert result.disposition == Disposition.NOTIFY


def test_workspace_debug_artifacts_is_normal() -> None:
    item = _make_item(
        id="ws-debug-repo",
        icon="🐛",
        title="Debug artifacts found in 2 files",
        detail="app.py:5 breakpoint() · utils.js:12 console.log",
        metadata={"sensor_type": "workspace", "debug_artifacts": "true"},
    )
    [result] = triage([item])
    assert result.urgency == Urgency.NORMAL
    assert result.disposition == Disposition.NOTIFY


def test_workspace_preflight_failure_is_high() -> None:
    item = _make_item(
        id="ws-preflight-repo",
        icon="🚫",
        title="Preflight failed: lint",
        detail="eslint returned exit code 1",
        metadata={"sensor_type": "workspace", "preflight_failure": "true"},
    )
    [result] = triage([item])
    assert result.urgency == Urgency.HIGH
    assert result.disposition == Disposition.NOTIFY
