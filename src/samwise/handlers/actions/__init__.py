from __future__ import annotations

from samwise.config import Settings
from samwise.handlers.actions.base import Action, SafetyLevel
from samwise.handlers.actions.fix_lint import FixLintAction
from samwise.handlers.actions.merge_pr import MergePRAction
from samwise.handlers.actions.registry import ActionRegistry

__all__ = [
    "Action",
    "ActionRegistry",
    "FixLintAction",
    "MergePRAction",
    "SafetyLevel",
    "build_default_registry",
]


def build_default_registry(settings: Settings) -> ActionRegistry:
    """Construct the registry of actions Samwise can perform.

    Order matters: the first matching action handles the item.
    """
    return ActionRegistry(
        [
            FixLintAction(settings),
            MergePRAction(settings),
        ]
    )
