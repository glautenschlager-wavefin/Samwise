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
