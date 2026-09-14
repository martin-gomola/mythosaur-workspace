from __future__ import annotations

from typing import Any

from ...common import ToolDef, err, listify_strings, now_ms, ok, parse_int
from ..google_plugin import READ_TOOL, WRITE_TOOL
from . import _auth, _capabilities, _validation


def _calendar_events(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_calendar_events", "calendar_read", started)
    if blocked:
        return blocked
    time_min = (args.get("time_min") or "").strip()
    time_max = (args.get("time_max") or "").strip()
    calendar_id = (args.get("calendar_id") or "primary").strip() or "primary"
    max_results = parse_int(args.get("max_results"), 10, minimum=1, maximum=50)

    if not time_min or not time_max:
        return err("google_calendar_events", "missing_window", "time_min and time_max are required", "google", started)
    for field, val in [("time_min", time_min), ("time_max", time_max)]:
        ts_err = _validation._validate_rfc3339("google_calendar_events", field, val, started)
        if ts_err:
            return ts_err

    try:
        service = _auth._build_service("calendar", "v3", _capabilities.CALENDAR_SCOPES)
        payload = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
    except Exception as exc:
        return _validation._google_error("google_calendar_events", "calendar_failed", exc, started)

    events = []
    for item in payload.get("items") or []:
        start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
        end = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date")
        events.append(
            {
                "id": item.get("id"),
                "summary": item.get("summary", ""),
                "start": start,
                "end": end,
                "html_link": item.get("htmlLink", ""),
            }
        )
    return ok(
        "google_calendar_events",
        {
            "calendar_id": calendar_id,
            "time_min": time_min,
            "time_max": time_max,
            "events": events,
        },
        "google",
        started,
    )


def _calendar_create_event(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_calendar_create_event", "calendar_write", started)
    if blocked:
        return blocked

    calendar_id = (args.get("calendar_id") or "primary").strip() or "primary"
    summary = (args.get("summary") or "").strip()
    description = (args.get("description") or "").strip()
    location = (args.get("location") or "").strip()
    timezone = (args.get("timezone") or "UTC").strip() or "UTC"
    start_time = (args.get("start_time") or "").strip()
    end_time = (args.get("end_time") or "").strip()
    start_date = (args.get("start_date") or "").strip()
    end_date = (args.get("end_date") or "").strip()
    attendees = listify_strings(args.get("attendees"))
    recurrence = listify_strings(args.get("recurrence"))

    if not summary:
        return err(
            "google_calendar_create_event",
            "missing_args",
            "summary is required",
            "google",
            started,
        )

    body: dict[str, Any] = {"summary": summary}
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        email_err = _validation._validate_emails("google_calendar_create_event", "attendees", attendees, started)
        if email_err:
            return email_err
        body["attendees"] = [{"email": email} for email in attendees]
    if recurrence:
        body["recurrence"] = recurrence

    if start_time and end_time:
        body["start"] = {"dateTime": start_time, "timeZone": timezone}
        body["end"] = {"dateTime": end_time, "timeZone": timezone}
    elif start_date and end_date:
        body["start"] = {"date": start_date}
        body["end"] = {"date": end_date}
    else:
        return err(
            "google_calendar_create_event",
            "missing_window",
            "provide either start_time and end_time, or start_date and end_date",
            "google",
            started,
        )

    try:
        send_updates = _validation._validate_enum(
            (args.get("send_updates") or "none").strip(), _validation._VALID_SEND_UPDATES, "none",
        )
        service = _auth._build_service("calendar", "v3", _capabilities.CALENDAR_WRITE_SCOPES)
        payload = (
            service.events()
            .insert(calendarId=calendar_id, body=body, sendUpdates=send_updates)
            .execute()
        )
    except Exception as exc:
        return _validation._google_error("google_calendar_create_event", "calendar_create_failed", exc, started)

    event_start = payload.get("start", {}).get("dateTime") or payload.get("start", {}).get("date")
    event_end = payload.get("end", {}).get("dateTime") or payload.get("end", {}).get("date")
    return ok(
        "google_calendar_create_event",
        {
            "id": payload.get("id"),
            "calendar_id": calendar_id,
            "summary": payload.get("summary", summary),
            "start": event_start,
            "end": event_end,
            "html_link": payload.get("htmlLink", ""),
            "attendee_count": len(payload.get("attendees") or attendees),
        },
        "google",
        started,
    )


def get_tools() -> list[ToolDef]:
    return [
        READ_TOOL(
            name="google_calendar_events",
            description="List Google Calendar events in a time window.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "time_min": {"type": "string", "description": "Start of time window in RFC 3339 format (e.g. '2025-03-18T00:00:00Z')."},
                    "time_max": {"type": "string", "description": "End of time window in RFC 3339 format."},
                    "calendar_id": {"type": "string", "description": "Calendar ID. Defaults to 'primary'."},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10, "description": "Maximum events to return (1-50). Defaults to 10."},
                },
                "required": ["time_min", "time_max"],
            },
            handler=_calendar_events,
        ),
        WRITE_TOOL(
            name="google_calendar_create_event",
            description="Create a new Google Calendar event with title, times, location, and optional attendees.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "calendar_id": {"type": "string", "description": "Calendar ID. Defaults to 'primary'."},
                    "summary": {"type": "string", "description": "Event title/summary."},
                    "description": {"type": "string", "description": "Event description or notes."},
                    "location": {"type": "string", "description": "Event location."},
                    "timezone": {"type": "string", "description": "IANA timezone for the event (e.g. 'Europe/Bratislava'). Defaults to UTC."},
                    "start_time": {"type": "string", "description": "Start date-time in RFC 3339 (e.g. '2025-03-18T10:00:00+01:00'). Use with end_time for timed events."},
                    "end_time": {"type": "string", "description": "End date-time in RFC 3339. Use with start_time."},
                    "start_date": {"type": "string", "description": "Start date for all-day events (YYYY-MM-DD). Use with end_date."},
                    "end_date": {"type": "string", "description": "End date for all-day events (YYYY-MM-DD, exclusive). Use with start_date."},
                    "attendees": {"type": "array", "items": {"type": "string"}, "description": "Email addresses of attendees to invite."},
                    "recurrence": {"type": "array", "items": {"type": "string"}, "description": "RRULE strings for recurring events (e.g. ['RRULE:FREQ=WEEKLY;COUNT=5'])."},
                    "send_updates": {"type": "string", "enum": ["all", "externalOnly", "none"], "description": "Who to notify: 'all', 'externalOnly', or 'none'. Defaults to 'none'."},
                },
                "required": ["summary"],
            },
            handler=_calendar_create_event,
            audit_action="google_calendar_create_event",
        ),
    ]
