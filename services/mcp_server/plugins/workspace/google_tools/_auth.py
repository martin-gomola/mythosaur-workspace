"""Google auth and service builder helpers."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Final

from ...common import env_get, err
from ._validation import GOOGLE_SOURCE

DEFAULT_TOKEN_FILE: Final = "/secrets/google-token.json"
DEFAULT_CREDENTIALS_FILE: Final = "/secrets/google-credentials.json"

_token_refresh_lock = threading.Lock()


class GoogleReauthRequired(RuntimeError):
    pass


def write_token_json(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            os.chmod(temporary.name, 0o600)
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def google_modules():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    return Request, Credentials, build


def token_file() -> Path:
    raw = (env_get("MW_GOOGLE_TOKEN_FILE", DEFAULT_TOKEN_FILE) or DEFAULT_TOKEN_FILE).strip()
    return Path(raw)


def credentials_file() -> Path:
    raw = (env_get("MW_GOOGLE_CREDENTIALS_FILE", DEFAULT_CREDENTIALS_FILE) or DEFAULT_CREDENTIALS_FILE).strip()
    return Path(raw)


def get_credentials(scopes: list[str]):
    Request, Credentials, _build = google_modules()
    from google.auth.exceptions import RefreshError

    path = token_file()
    if not path.exists():
        raise GoogleReauthRequired("Google authorization is required")
    with _token_refresh_lock:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            raw_scopes = payload.get("scopes") or payload.get("scope") or []
            granted_scopes = set(raw_scopes.split() if isinstance(raw_scopes, str) else raw_scopes)
            if not set(scopes).issubset(granted_scopes):
                raise GoogleReauthRequired("Google authorization is missing required scopes")
            creds = Credentials.from_authorized_user_info(payload, scopes)
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                write_token_json(path, creds.to_json())
        except GoogleReauthRequired:
            raise
        except (OSError, ValueError, RefreshError) as exc:
            raise GoogleReauthRequired("Google authorization must be refreshed") from exc
    if not creds.valid:
        raise GoogleReauthRequired("Google authorization is missing required scopes")
    return creds


def build_service(name: str, version: str, scopes: list[str]):
    _Request, _Credentials, build = google_modules()
    creds = get_credentials(scopes)
    return build(name, version, credentials=creds, cache_discovery=False)


def maps_api_key_value() -> str:
    direct = (env_get("MW_GOOGLE_MAPS_API_KEY", "") or "").strip()
    if direct:
        return direct

    compatible = (env_get("GOOGLE_MAPS_API_KEY", "") or "").strip()
    if compatible:
        return compatible

    legacy = (env_get("MW_GOOGLE_MAPS_PLATFORM", "") or "").strip()
    if legacy.startswith("AIza"):
        return legacy
    return ""


def maps_referrer_value() -> str:
    direct = (env_get("MW_GOOGLE_MAPS_REFERER", "") or "").strip()
    if direct:
        return direct
    return (env_get("GOOGLE_MAPS_REFERER", "") or "").strip()


def maps_api_guard(tool_name: str, started: int) -> dict[str, Any] | None:
    if maps_api_key_value():
        return None
    return err(
        tool_name,
        "maps_api_key_missing",
        "Google Maps API key is not configured. Set MW_GOOGLE_MAPS_API_KEY.",
        GOOGLE_SOURCE,
        started,
    )


_google_modules = google_modules
_token_file = token_file
_credentials_file = credentials_file
_get_credentials = get_credentials
_write_token_json = write_token_json
_build_service = build_service
_maps_api_key_value = maps_api_key_value
_maps_referrer_value = maps_referrer_value
_maps_api_guard = maps_api_guard


def __getattr__(name: str):
    capability_names = {
        "GOOGLE_PLUGIN_ID",
        "CALENDAR_SCOPES",
        "CALENDAR_WRITE_SCOPES",
        "GMAIL_SCOPES",
        "GMAIL_SEND_SCOPES",
        "DRIVE_SCOPES",
        "DRIVE_WRITE_SCOPES",
        "SHEETS_SCOPES",
        "SHEETS_WRITE_SCOPES",
        "DOCS_SCOPES",
        "DOCS_WRITE_SCOPES",
        "PHOTOS_READ_SCOPES",
        "PHOTOS_WRITE_SCOPES",
        "_MAPS_DEFAULT_TIMEOUT_SEC",
        "_PHOTOS_DEFAULT_TIMEOUT_SEC",
        "_GOOGLE_SCOPE_REQUIREMENTS",
        "google_capabilities",
        "google_auth_status",
        "_google_service_checks",
        "_granted_scopes",
        "_scope_checks",
        "_capability_guard",
    }
    validation_names = {
        "GOOGLE_SOURCE",
        "_MAX_CONTENT_BYTES",
        "_MAX_UPLOAD_BYTES",
        "_MAX_LABEL_IDS",
        "_MAX_DRIVE_QUERY_LEN",
        "_MIME_TYPE_RE",
        "_HTML_DANGEROUS_RE",
        "_VALID_SEND_UPDATES",
        "_VALID_VALUE_INPUT_OPTIONS",
        "_VALID_INSERT_DATA_OPTIONS",
        "_VALID_ROUTING_PREFERENCES",
        "_safe_error_msg",
        "_validate_emails",
        "_validate_rfc3339",
        "_validate_content_size",
        "_validate_enum",
    }
    if name in capability_names:
        from . import _capabilities

        return getattr(_capabilities, name)
    if name in validation_names:
        from . import _validation

        return getattr(_validation, name)
    raise AttributeError(name)
