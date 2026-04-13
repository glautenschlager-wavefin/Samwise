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
