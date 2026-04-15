"""Google Calendar sensor — polls upcoming events."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from samwise.config import Settings
from samwise.models import ActivityCategory, ActivityItem, Urgency
from samwise.sensors.base import Sensor

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/calendar.events.readonly"]
_CALENDAR_API = "https://www.googleapis.com/calendar/v3"


class CalendarSensor(Sensor):
    """Poll Google Calendar for events happening soon."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._token_path = settings.data_dir / "google_token.json"
        self._client = httpx.AsyncClient(timeout=15.0)

    async def poll(self) -> list[ActivityItem]:
        creds = await self._load_credentials()
        if creds is None:
            return []

        now = datetime.now(UTC)
        time_max = now + timedelta(hours=2)

        try:
            resp = await self._client.get(
                f"{_CALENDAR_API}/calendars/primary/events",
                params={
                    "timeMin": now.isoformat(),
                    "timeMax": time_max.isoformat(),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": "10",
                },
                headers={"Authorization": f"Bearer {creds.token}"},
            )
            if resp.status_code == 403:
                body = resp.json()
                error_msg = body.get("error", {}).get("message", resp.text)
                logger.error("Google Calendar 403: %s", error_msg)
                logger.error(
                    "Likely fix: enable the Google Calendar API at "
                    "https://console.cloud.google.com/apis/library/calendar-json.googleapis.com"
                )
                return []
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Google Calendar API error during poll")
            return []

        data: dict[str, Any] = resp.json()
        items: list[ActivityItem] = []

        for event in data.get("items", []):
            item = self._parse_event(event, now)
            if item is not None:
                items.append(item)

        logger.info("Calendar sensor: %d upcoming events", len(items))
        return items

    # ------------------------------------------------------------------

    def _parse_event(self, event: dict[str, Any], now: datetime) -> ActivityItem | None:
        if event.get("status") == "cancelled":
            return None

        # Skip events the user declined.
        for att in event.get("attendees", []):
            if att.get("self") and att.get("responseStatus") == "declined":
                return None

        # Skip all-day events (no dateTime, only date).
        start_raw: dict[str, str] = event.get("start", {})
        if "dateTime" not in start_raw:
            return None

        start = datetime.fromisoformat(start_raw["dateTime"])
        end_raw: dict[str, str] = event.get("end", {})
        end = (
            datetime.fromisoformat(end_raw["dateTime"])
            if "dateTime" in end_raw
            else start + timedelta(hours=1)
        )

        minutes_until = (start - now).total_seconds() / 60
        summary = event.get("summary", "Untitled event")
        num_attendees = len(event.get("attendees", []))

        # Icon & time label
        if minutes_until <= 0:
            time_label = "now"
            icon = "🟢"
        elif minutes_until <= 5:
            time_label = "starting now"
            icon = "🔴"
        elif minutes_until <= 15:
            time_label = f"in {int(minutes_until)} min"
            icon = "🟡"
        else:
            time_label = f"in {int(minutes_until)} min"
            icon = "📅"

        title = f"{summary} ({time_label})"

        # Detail line
        time_fmt = start.strftime("%-I:%M %p")
        end_fmt = end.strftime("%-I:%M %p")
        detail_parts = [f"{time_fmt} – {end_fmt}"]
        if num_attendees > 1:
            detail_parts.append(f"{num_attendees} attendees")
        if event.get("location"):
            detail_parts.append(str(event["location"]))
        elif event.get("hangoutLink"):
            detail_parts.append("Google Meet")
        detail = " · ".join(detail_parts)

        # Urgency by proximity
        if minutes_until <= 5:
            urgency = Urgency.HIGH
        elif minutes_until <= 30:
            urgency = Urgency.NORMAL
        else:
            urgency = Urgency.LOW

        return ActivityItem(
            id=f"gcal-{event['id']}",
            category=ActivityCategory.CALENDAR,
            icon=icon,
            title=title,
            detail=detail,
            timestamp=start,
            urgency=urgency,
            metadata={
                "event_id": str(event["id"]),
                "minutes_until": str(int(minutes_until)),
                "attendees": str(num_attendees),
            },
        )

    # ------------------------------------------------------------------

    async def _load_credentials(self) -> Credentials | None:
        if not self._token_path.exists():
            logger.warning(
                "No Google Calendar token — run `make auth-google` to authenticate"
            )
            return None

        try:
            creds: Credentials = await asyncio.to_thread(
                Credentials.from_authorized_user_file,
                str(self._token_path),
                _SCOPES,
            )
        except Exception:
            logger.exception("Failed to load Google credentials")
            return None

        if creds.expired and creds.refresh_token:
            try:
                await asyncio.to_thread(creds.refresh, Request())
                self._token_path.write_text(creds.to_json())  # type: ignore[no-untyped-call]
            except Exception:
                logger.exception(
                    "Failed to refresh Google token — re-run `make auth-google`"
                )
                return None

        if not creds.valid:
            logger.warning("Google credentials invalid — re-run `make auth-google`")
            return None

        return creds

    async def close(self) -> None:
        await self._client.aclose()
