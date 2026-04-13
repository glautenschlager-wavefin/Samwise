from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class ActivityCategory(StrEnum):
    CODE_SHIPPING = "code-shipping"
    COMMS = "comms"
    BREAK = "break"
    SPRINT = "sprint"


class ActivityItem(BaseModel):
    id: str
    category: ActivityCategory
    icon: str
    title: str
    detail: str
    timestamp: datetime


class StatusSummary(BaseModel):
    text: str
    tooltip: str


class HealthResponse(BaseModel):
    status: str
    version: str
