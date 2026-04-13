from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class ActivityCategory(StrEnum):
    CODE_SHIPPING = "code-shipping"
    COMMS = "comms"
    BREAK = "break"
    SPRINT = "sprint"


class Urgency(StrEnum):
    HIGH = "high"  # surface immediately
    NORMAL = "normal"  # show in next feed refresh
    LOW = "low"  # batch for later


class Disposition(StrEnum):
    NOTIFY = "notify"  # push to the user
    DEFER = "defer"  # store silently, surface later
    ACT = "act"  # Samwise should handle autonomously


class ActivityItem(BaseModel):
    id: str
    category: ActivityCategory
    icon: str
    title: str
    detail: str
    timestamp: datetime
    urgency: Urgency = Urgency.NORMAL
    disposition: Disposition = Disposition.NOTIFY


class StatusSummary(BaseModel):
    text: str
    tooltip: str


class HealthResponse(BaseModel):
    status: str
    version: str
