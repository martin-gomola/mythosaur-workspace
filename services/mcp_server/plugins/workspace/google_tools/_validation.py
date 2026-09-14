from __future__ import annotations

import re
from typing import Any, Final

import requests

from ...common import err

GOOGLE_SOURCE: Final = "google"
_MAX_CONTENT_BYTES = 10 * 1024 * 1024
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_MAX_LABEL_IDS = 20
_MAX_DRIVE_QUERY_LEN = 1000

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_RFC3339_LIKE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:\d{2})?)?$"
)
_MIME_TYPE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9!#$&\-^_.+]*/[a-zA-Z0-9][a-zA-Z0-9!#$&\-^_.+]*$")
_HTML_DANGEROUS_RE = re.compile(
    r"<\s*script|javascript\s*:|on\w+\s*=|<\s*iframe|<\s*object|<\s*embed|<\s*applet|<\s*form\b",
    re.IGNORECASE,
)

_VALID_SEND_UPDATES = frozenset({"all", "externalOnly", "none"})
_VALID_VALUE_INPUT_OPTIONS = frozenset({"USER_ENTERED", "RAW"})
_VALID_INSERT_DATA_OPTIONS = frozenset({"INSERT_ROWS", "OVERWRITE"})
_VALID_ROUTING_PREFERENCES = frozenset({"TRAFFIC_UNAWARE", "TRAFFIC_AWARE", "TRAFFIC_AWARE_OPTIMAL"})


def safe_error_msg(exc: Exception) -> str:
    if isinstance(exc, requests.RequestException):
        resp = getattr(exc, "response", None)
        if resp is not None:
            try:
                body = resp.json()
                msg = ((body.get("error") or {}).get("message")) or ""
                if msg:
                    return msg[:500]
            except (ValueError, AttributeError):
                pass
            if hasattr(resp, "text") and resp.text:
                return resp.text[:500]
        return "Google API request failed"
    if isinstance(exc, (FileNotFoundError, ValueError)):
        return str(exc)[:500]
    return "an unexpected error occurred"


def google_error(
    tool_name: str,
    default_code: str,
    exc: Exception,
    started: int,
) -> dict[str, Any]:
    from google.auth.exceptions import RefreshError

    from ._auth import GoogleReauthRequired

    response = getattr(exc, "response", None)
    if response is None:
        response = getattr(exc, "resp", None)
    status = getattr(response, "status_code", None) or getattr(response, "status", None)
    permission_failure = status == 403 and any(
        marker in str(exc).lower() for marker in ("insufficient", "permission", "scope")
    )
    if isinstance(exc, (GoogleReauthRequired, RefreshError)) or status == 401 or permission_failure:
        return err(
            tool_name,
            "reauth_required",
            "Google authorization is required. Use Codex Authenticate or run make login.",
            GOOGLE_SOURCE,
            started,
        )
    return err(tool_name, default_code, safe_error_msg(exc), GOOGLE_SOURCE, started)


def validate_emails(tool_name: str, field: str, emails: list[str], started: int) -> dict[str, Any] | None:
    for addr in emails:
        if not _EMAIL_RE.match(addr):
            return err(tool_name, "invalid_email", f"invalid email in {field}: {addr}", GOOGLE_SOURCE, started)
    return None


def validate_rfc3339(tool_name: str, field: str, value: str, started: int) -> dict[str, Any] | None:
    if value and not _RFC3339_LIKE_RE.match(value):
        return err(tool_name, "invalid_timestamp", f"{field} must be RFC 3339 format", GOOGLE_SOURCE, started)
    return None


def validate_content_size(
    tool_name: str, content: str, max_bytes: int, started: int,
) -> dict[str, Any] | None:
    size = len(content.encode("utf-8"))
    if size > max_bytes:
        return err(
            tool_name, "content_too_large",
            f"content is {size} bytes, max allowed is {max_bytes}",
            GOOGLE_SOURCE, started,
        )
    return None


def validate_enum(value: str, valid: frozenset[str], default: str) -> str:
    return value if value in valid else default


_safe_error_msg = safe_error_msg
_google_error = google_error
_validate_emails = validate_emails
_validate_rfc3339 = validate_rfc3339
_validate_content_size = validate_content_size
_validate_enum = validate_enum
