from __future__ import annotations

import json
from typing import Any, Final

from ...common import JsonDict, bool_env, err
from . import _auth
from ._validation import GOOGLE_SOURCE

GOOGLE_PLUGIN_ID = "mythosaur.google_workspace"

CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
CALENDAR_WRITE_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_SEND_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"]
DRIVE_WRITE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SHEETS_WRITE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
DOCS_SCOPES = ["https://www.googleapis.com/auth/documents.readonly"]
DOCS_WRITE_SCOPES = ["https://www.googleapis.com/auth/documents"]
PHOTOS_READ_SCOPES = ["https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata"]
PHOTOS_WRITE_SCOPES = [
    "https://www.googleapis.com/auth/photoslibrary.appendonly",
    "https://www.googleapis.com/auth/photoslibrary.edit.appcreateddata",
]

_MAPS_DEFAULT_TIMEOUT_SEC = 20
_PHOTOS_DEFAULT_TIMEOUT_SEC = 20

_GOOGLE_SCOPE_REQUIREMENTS: Final = {
    "gmail_read": GMAIL_SCOPES,
    "gmail_send": GMAIL_SEND_SCOPES,
    "calendar_read": CALENDAR_SCOPES,
    "calendar_write": CALENDAR_WRITE_SCOPES,
    "drive_read": DRIVE_SCOPES,
    "drive_write": DRIVE_WRITE_SCOPES,
    "sheets_read": SHEETS_SCOPES,
    "sheets_write": SHEETS_WRITE_SCOPES,
    "docs_read": DOCS_SCOPES,
    "docs_write": DOCS_WRITE_SCOPES,
    "photos_read": PHOTOS_READ_SCOPES,
    "photos_write": PHOTOS_WRITE_SCOPES,
}


def google_service_checks() -> dict[str, dict[str, Any]]:
    maps_api_key = _auth.maps_api_key_value()
    return {
        "maps": {
            "auth_type": "api_key",
            "configured": bool(maps_api_key),
            "required_config": ["MW_GOOGLE_MAPS_API_KEY"],
            "missing_config": [] if maps_api_key else ["MW_GOOGLE_MAPS_API_KEY"],
        }
    }


def google_capabilities() -> dict[str, bool]:
    return {
        "calendar_read": bool_env("MW_GOOGLE_CALENDAR_READ_ENABLED", True),
        "calendar_write": bool_env("MW_GOOGLE_CALENDAR_WRITE_ENABLED", False),
        "gmail_read": bool_env("MW_GOOGLE_GMAIL_READ_ENABLED", True),
        "gmail_send": bool_env("MW_GOOGLE_GMAIL_SEND_ENABLED", False),
        "drive_read": bool_env("MW_GOOGLE_DRIVE_READ_ENABLED", True),
        "drive_write": bool_env("MW_GOOGLE_DRIVE_WRITE_ENABLED", False),
        "sheets_read": bool_env("MW_GOOGLE_SHEETS_READ_ENABLED", True),
        "sheets_write": bool_env("MW_GOOGLE_SHEETS_WRITE_ENABLED", False),
        "docs_read": bool_env("MW_GOOGLE_DOCS_READ_ENABLED", True),
        "docs_write": bool_env("MW_GOOGLE_DOCS_WRITE_ENABLED", False),
        "photos_read": bool_env("MW_GOOGLE_PHOTOS_READ_ENABLED", False),
        "photos_write": bool_env("MW_GOOGLE_PHOTOS_WRITE_ENABLED", False),
        "notebooklm": bool_env("MW_NOTEBOOKLM_ENABLED", True),
        "maps": bool_env("MW_GOOGLE_MAPS_ENABLED", True),
    }


def granted_scopes(payload: JsonDict) -> list[str]:
    raw_scopes = payload.get("scopes") or payload.get("scope") or []
    if isinstance(raw_scopes, str):
        return [item.strip() for item in raw_scopes.split() if item.strip()]
    if isinstance(raw_scopes, list):
        return [str(item).strip() for item in raw_scopes if str(item).strip()]
    return []


def scope_checks(granted_scope_values: list[str]) -> dict[str, JsonDict]:
    granted = set(granted_scope_values)
    checks: dict[str, JsonDict] = {}
    for capability, required in _GOOGLE_SCOPE_REQUIREMENTS.items():
        missing = [scope for scope in required if scope not in granted]
        checks[capability] = {
            "required_scopes": list(required),
            "granted": not missing,
            "missing_scopes": missing,
        }
    return checks


def google_auth_status() -> JsonDict:
    token_file = _auth.token_file()
    service_checks = google_service_checks()
    if not token_file.exists():
        return {
            "mode": "oauth",
            "configured": False,
            "token_file": str(token_file),
            "token_present": False,
            "granted_scopes": [],
            "scope_checks": {},
            "service_checks": service_checks,
        }

    try:
        payload = json.loads(token_file.read_text(encoding="utf-8"))
    except Exception:
        return {
            "mode": "oauth",
            "configured": False,
            "token_file": str(token_file),
            "token_present": True,
            "granted_scopes": [],
            "scope_checks": {},
            "service_checks": service_checks,
            "error": "invalid token file: unable to parse token JSON",
        }

    scopes = granted_scopes(payload)
    return {
        "mode": "oauth",
        "configured": True,
        "token_file": str(token_file),
        "token_present": True,
        "granted_scopes": scopes,
        "scope_checks": scope_checks(scopes),
        "service_checks": service_checks,
    }


def capability_guard(tool_name: str, capability_key: str, started: int) -> dict[str, Any] | None:
    caps = google_capabilities()
    if caps.get(capability_key, False):
        return None
    return err(
        tool_name,
        "capability_disabled",
        f"Google capability '{capability_key}' is disabled by configuration.",
        GOOGLE_SOURCE,
        started,
    )


_google_service_checks = google_service_checks
_granted_scopes = granted_scopes
_scope_checks = scope_checks
_capability_guard = capability_guard
