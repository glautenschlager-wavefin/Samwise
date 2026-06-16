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
    """An approved PR is a merge opportunity — route to act handler."""
    if "approved" in item.title.lower():
        return item.model_copy(update={"urgency": Urgency.HIGH, "disposition": Disposition.ACT})
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


# ---------------------------------------------------------------------------
# Sprint / Jira rules
# ---------------------------------------------------------------------------


def _flagged_issue_is_high(item: ActivityItem) -> ActivityItem:
    """Flagged/blocked Jira issues need immediate attention."""
    if item.category == "sprint" and "flagged" in item.title.lower():
        return item.model_copy(update={"urgency": Urgency.HIGH})
    return item


def _highest_priority_issue_is_high(item: ActivityItem) -> ActivityItem:
    """Jira issues with Highest/Critical priority are high urgency."""
    if item.category == "sprint" and item.metadata.get("priority") in ("Highest", "Critical"):
        return item.model_copy(update={"urgency": Urgency.HIGH})
    return item


def _status_transition_is_normal(item: ActivityItem) -> ActivityItem:
    """Status transitions on your tickets are worth a notification."""
    if item.category == "sprint" and "moved to" in item.title.lower():
        return item.model_copy(update={"urgency": Urgency.NORMAL, "disposition": Disposition.NOTIFY})
    return item


def _low_priority_sprint_is_low(item: ActivityItem) -> ActivityItem:
    """Low/Lowest priority sprint items can be deferred."""
    if item.category == "sprint" and item.metadata.get("priority") in ("Low", "Lowest"):
        return item.model_copy(update={"urgency": Urgency.LOW})
    return item


# ---------------------------------------------------------------------------
# Calendar rules
# ---------------------------------------------------------------------------


def _meeting_imminent_is_high(item: ActivityItem) -> ActivityItem:
    """Meetings starting in 5 minutes or less are high urgency."""
    if item.category == "calendar":
        mins = int(item.metadata.get("minutes_until", "999"))
        if mins <= 5:
            return item.model_copy(update={"urgency": Urgency.HIGH})
    return item


def _distant_meeting_is_low(item: ActivityItem) -> ActivityItem:
    """Meetings more than 60 minutes away can be deferred."""
    if item.category == "calendar":
        mins = int(item.metadata.get("minutes_until", "0"))
        if mins > 60:
            return item.model_copy(
                update={"urgency": Urgency.LOW, "disposition": Disposition.DEFER}
            )
    return item


# ---------------------------------------------------------------------------
# Project rules
# ---------------------------------------------------------------------------


def _project_stale_is_high(item: ActivityItem) -> ActivityItem:
    """Stale side projects (no push beyond threshold) need aggressive nudging."""
    if item.category == "project" and item.metadata.get("staleness") == "stale":
        return item.model_copy(update={"urgency": Urgency.HIGH, "disposition": Disposition.NOTIFY})
    return item


def _project_issue_no_assignee(item: ActivityItem) -> ActivityItem:
    """Open project issues with no assignee are normal priority."""
    if item.category == "project" and item.metadata.get("issue_number"):
        return item.model_copy(update={"urgency": Urgency.NORMAL, "disposition": Disposition.NOTIFY})
    return item


def _project_active_burst(item: ActivityItem) -> ActivityItem:
    """During an active burst (pushed today), surface open issues as next tasks."""
    if item.category == "project" and item.metadata.get("burst") == "true":
        return item.model_copy(update={"urgency": Urgency.NORMAL, "disposition": Disposition.NOTIFY})
    return item


def _project_issues_summary_is_low(item: ActivityItem) -> ActivityItem:
    """Open issue summaries (not in a burst) are low urgency background info."""
    if (
        item.category == "project"
        and item.metadata.get("open_count")
        and not item.metadata.get("burst")
    ):
        return item.model_copy(update={"urgency": Urgency.LOW, "disposition": Disposition.DEFER})
    return item


def _project_progress_is_low(item: ActivityItem) -> ActivityItem:
    """Recently closed issues are positive reinforcement — low urgency, defer."""
    if item.category == "project" and item.metadata.get("progress") == "true":
        return item.model_copy(update={"urgency": Urgency.LOW, "disposition": Disposition.DEFER})
    return item


def _project_pr_stale(item: ActivityItem) -> ActivityItem:
    """Stale pull requests (including drafts) need a nudge."""
    if item.category == "project" and item.metadata.get("pr_stale") == "true":
        return item.model_copy(update={"urgency": Urgency.HIGH, "disposition": Disposition.NOTIFY})
    return item


# ---------------------------------------------------------------------------
# PR SLA rules
# ---------------------------------------------------------------------------


def _sla_pr_too_large(item: ActivityItem) -> ActivityItem:
    """PRs exceeding the line limit need to be split."""
    if item.metadata.get("sla_violation") == "size":
        return item.model_copy(update={"urgency": Urgency.HIGH, "disposition": Disposition.NOTIFY})
    return item


def _sla_pr_aging(item: ActivityItem) -> ActivityItem:
    """PRs open too long need to be merged or closed."""
    if item.metadata.get("sla_violation") == "age":
        return item.model_copy(update={"urgency": Urgency.HIGH, "disposition": Disposition.NOTIFY})
    return item


def _sla_pr_needs_review(item: ActivityItem) -> ActivityItem:
    """PRs with many commits but no review need attention."""
    if item.metadata.get("sla_violation") == "review_wait":
        return item.model_copy(update={"urgency": Urgency.NORMAL, "disposition": Disposition.NOTIFY})
    return item


# ---------------------------------------------------------------------------
# Workspace rules
# ---------------------------------------------------------------------------


def _workspace_conflict_warning(item: ActivityItem) -> ActivityItem:
    """Merge conflict warnings are high urgency."""
    if item.metadata.get("conflict_warning") == "true":
        return item.model_copy(update={"urgency": Urgency.HIGH, "disposition": Disposition.NOTIFY})
    return item


def _workspace_divergence(item: ActivityItem) -> ActivityItem:
    """Branch divergence (no conflicts yet) is a normal nudge."""
    if item.metadata.get("divergence_warning") == "true":
        return item.model_copy(update={"urgency": Urgency.NORMAL, "disposition": Disposition.NOTIFY})
    return item


def _workspace_unpushed(item: ActivityItem) -> ActivityItem:
    """Unpushed commits are informational."""
    if item.metadata.get("sensor_type") == "workspace" and item.metadata.get("unpushed"):
        return item.model_copy(update={"urgency": Urgency.LOW, "disposition": Disposition.NOTIFY})
    return item


def _workspace_debug_artifacts(item: ActivityItem) -> ActivityItem:
    """Debug artifacts left in code should be cleaned before shipping."""
    if item.metadata.get("debug_artifacts") == "true":
        return item.model_copy(update={"urgency": Urgency.NORMAL, "disposition": Disposition.NOTIFY})
    return item


def _workspace_preflight_failure(item: ActivityItem) -> ActivityItem:
    """Preflight failures (lint/test) need fixing before pushing.

    Lint failures are routed to ACT so Samwise can auto-fix them; other
    checks (e.g. tests) still surface as a NOTIFY for the user to handle.
    """
    if item.metadata.get("preflight_failure") == "true":
        disposition = (
            Disposition.ACT
            if item.metadata.get("check") == "lint"
            else Disposition.NOTIFY
        )
        return item.model_copy(update={"urgency": Urgency.HIGH, "disposition": disposition})
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
    _flagged_issue_is_high,
    _highest_priority_issue_is_high,
    _status_transition_is_normal,
    _low_priority_sprint_is_low,
    _meeting_imminent_is_high,
    _distant_meeting_is_low,
    _project_stale_is_high,
    _project_active_burst,
    _project_issue_no_assignee,
    _project_issues_summary_is_low,
    _project_progress_is_low,
    _project_pr_stale,
    _sla_pr_too_large,
    _sla_pr_aging,
    _sla_pr_needs_review,
    _workspace_conflict_warning,
    _workspace_divergence,
    _workspace_unpushed,
    _workspace_debug_artifacts,
    _workspace_preflight_failure,
]
