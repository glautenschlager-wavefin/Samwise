from __future__ import annotations

import logging
from collections.abc import Callable

from samwise.models import ActivityItem, Disposition, Urgency

logger = logging.getLogger(__name__)

TriageRule = Callable[[ActivityItem], ActivityItem]


def triage(items: list[ActivityItem]) -> list[ActivityItem]:
    """Apply triage rules to raw sensor events.

    Each rule can mutate urgency and disposition on an item.
    Rules are applied in order; later rules can override earlier ones.
    """
    triaged: list[ActivityItem] = []
    for item in items:
        result = item.model_copy()
        for rule in _RULES:
            result = rule(result)
        triaged.append(result)

    logger.info(
        "Triaged %d items: %d notify, %d defer, %d act",
        len(triaged),
        sum(1 for i in triaged if i.disposition == Disposition.NOTIFY),
        sum(1 for i in triaged if i.disposition == Disposition.DEFER),
        sum(1 for i in triaged if i.disposition == Disposition.ACT),
    )
    return triaged


# ---------------------------------------------------------------------------
# Triage rules — each takes an item and returns a (possibly modified) copy.
# ---------------------------------------------------------------------------


def _ci_failure_is_high_urgency(item: ActivityItem) -> ActivityItem:
    """CI failures on your PRs need immediate attention."""
    if "CI" in item.title and ("fail" in item.title.lower() or item.icon == "🔴"):
        return item.model_copy(update={"urgency": Urgency.HIGH})
    return item


def _pr_approved_is_high(item: ActivityItem) -> ActivityItem:
    """An approved PR is a merge opportunity — don't let it go stale."""
    if "approved" in item.title.lower():
        return item.model_copy(update={"urgency": Urgency.HIGH})
    return item


def _review_request_is_normal(item: ActivityItem) -> ActivityItem:
    """Someone wants your review — normal priority."""
    if "review" in item.title.lower() and "request" in item.title.lower():
        return item.model_copy(update={"urgency": Urgency.NORMAL})
    return item


def _open_pr_no_action_is_low(item: ActivityItem) -> ActivityItem:
    """Open PRs with no new activity are low-priority background info."""
    if "open" in item.title.lower() and item.icon == "🔄":
        return item.model_copy(update={"urgency": Urgency.LOW, "disposition": Disposition.DEFER})
    return item


def _changes_requested_is_high(item: ActivityItem) -> ActivityItem:
    """Changes requested on your PR — you need to act."""
    if "changes" in item.title.lower() and "request" in item.detail.lower():
        return item.model_copy(update={"urgency": Urgency.HIGH})
    return item


def _break_reminder_is_normal(item: ActivityItem) -> ActivityItem:
    """Break reminders are always notify, normal urgency."""
    if item.category == "break":
        return item.model_copy(
            update={"urgency": Urgency.NORMAL, "disposition": Disposition.NOTIFY}
        )
    return item


def _notification_mention_is_high(item: ActivityItem) -> ActivityItem:
    """Direct mentions in GitHub are high urgency."""
    if "mention" in item.detail.lower() and item.icon == "💬":
        return item.model_copy(update={"urgency": Urgency.HIGH})
    return item


# Rule registry — order matters.
_RULES: list[TriageRule] = [
    _ci_failure_is_high_urgency,
    _pr_approved_is_high,
    _review_request_is_normal,
    _open_pr_no_action_is_low,
    _changes_requested_is_high,
    _break_reminder_is_normal,
    _notification_mention_is_high,
]
