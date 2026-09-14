from __future__ import annotations

import mimetypes
from typing import Any

from ...common import ToolDef, err, now_ms, ok, parse_int, resolve_under_shared
from ..google_plugin import READ_TOOL, WRITE_TOOL
from . import _auth, _capabilities, _validation

# Setting a Google-native mimeType on the file metadata makes Drive convert the
# uploaded bytes on ingest, e.g. .pptx -> Google Slides.
_CONVERT_TARGETS = {
    "presentation": "application/vnd.google-apps.presentation",
    "document": "application/vnd.google-apps.document",
    "spreadsheet": "application/vnd.google-apps.spreadsheet",
}


def _drive_recent_files(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_drive_recent_files", "drive_read", started)
    if blocked:
        return blocked
    max_results = parse_int(args.get("max_results"), 10, minimum=1, maximum=50)
    query = (args.get("query") or "").strip()
    if len(query) > _validation._MAX_DRIVE_QUERY_LEN:
        return err(
            "google_drive_recent_files", "query_too_long",
            f"query exceeds {_validation._MAX_DRIVE_QUERY_LEN} characters",
            "google", started,
        )

    try:
        service = _auth._build_service("drive", "v3", _capabilities.DRIVE_SCOPES)
        payload = (
            service.files()
            .list(
                pageSize=max_results,
                q=query or None,
                orderBy="modifiedTime desc",
                fields="files(id,name,mimeType,modifiedTime,webViewLink)",
            )
            .execute()
        )
    except Exception as exc:
        return _validation._google_error("google_drive_recent_files", "drive_failed", exc, started)

    return ok(
        "google_drive_recent_files",
        {"files": payload.get("files") or []},
        "google",
        started,
    )


def _drive_create_folder(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_drive_create_folder", "drive_write", started)
    if blocked:
        return blocked
    folder_name = (args.get("folder_name") or "").strip()
    parent_folder_id = (args.get("parent_folder_id") or "").strip()
    if not folder_name:
        return err(
            "google_drive_create_folder",
            "missing_args",
            "folder_name is required",
            "google",
            started,
        )

    metadata: dict[str, Any] = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_folder_id:
        metadata["parents"] = [parent_folder_id]

    try:
        service = _auth._build_service("drive", "v3", _capabilities.DRIVE_WRITE_SCOPES)
        payload = (
            service.files()
            .create(body=metadata, fields="id,name,mimeType,parents,webViewLink")
            .execute()
        )
    except Exception as exc:
        return _validation._google_error("google_drive_create_folder", "drive_create_failed", exc, started)

    return ok(
        "google_drive_create_folder",
        {
            "id": payload.get("id"),
            "name": payload.get("name", folder_name),
            "mime_type": payload.get("mimeType", ""),
            "parent_folder_id": parent_folder_id,
            "web_view_link": payload.get("webViewLink", ""),
        },
        "google",
        started,
    )


def _drive_create_text_file(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_drive_create_text_file", "drive_write", started)
    if blocked:
        return blocked
    file_name = (args.get("file_name") or "").strip()
    content = args.get("content")
    parent_folder_id = (args.get("parent_folder_id") or "").strip()
    mime_type = (args.get("mime_type") or "text/plain").strip() or "text/plain"

    if not file_name:
        return err(
            "google_drive_create_text_file",
            "missing_args",
            "file_name is required",
            "google",
            started,
        )
    if content is None:
        content = ""
    if not isinstance(content, str):
        return err(
            "google_drive_create_text_file",
            "invalid_content",
            "content must be a string",
            "google",
            started,
        )
    size_err = _validation._validate_content_size("google_drive_create_text_file", content, _validation._MAX_CONTENT_BYTES, started)
    if size_err:
        return size_err
    if mime_type != "text/plain" and not _validation._MIME_TYPE_RE.match(mime_type):
        return err("google_drive_create_text_file", "invalid_mime_type", f"invalid mime_type: {mime_type}", "google", started)

    metadata: dict[str, Any] = {"name": file_name}
    if parent_folder_id:
        metadata["parents"] = [parent_folder_id]

    try:
        from googleapiclient.http import MediaInMemoryUpload

        service = _auth._build_service("drive", "v3", _capabilities.DRIVE_WRITE_SCOPES)
        media = MediaInMemoryUpload(content.encode("utf-8"), mimetype=mime_type, resumable=False)
        payload = (
            service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id,name,mimeType,size,parents,webViewLink,webContentLink",
            )
            .execute()
        )
    except Exception as exc:
        return _validation._google_error("google_drive_create_text_file", "drive_create_failed", exc, started)

    return ok(
        "google_drive_create_text_file",
        {
            "id": payload.get("id"),
            "name": payload.get("name", file_name),
            "mime_type": payload.get("mimeType", mime_type),
            "size": payload.get("size"),
            "parent_folder_id": parent_folder_id,
            "content_bytes": len(content.encode("utf-8")),
            "web_view_link": payload.get("webViewLink", ""),
            "web_content_link": payload.get("webContentLink", ""),
        },
        "google",
        started,
    )


def _drive_upload_file(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_drive_upload_file", "drive_write", started)
    if blocked:
        return blocked
    path_value = (args.get("path") or "").strip()
    file_name = (args.get("file_name") or "").strip()
    parent_folder_id = (args.get("parent_folder_id") or "").strip()
    mime_type = (args.get("mime_type") or "").strip()
    convert_to = (args.get("convert_to") or "").strip().lower()

    if convert_to and convert_to not in _CONVERT_TARGETS:
        return err(
            "google_drive_upload_file",
            "invalid_convert_to",
            f"convert_to must be one of: {', '.join(sorted(_CONVERT_TARGETS))}",
            "google",
            started,
        )

    if not path_value:
        return err(
            "google_drive_upload_file",
            "missing_args",
            "path is required",
            "google",
            started,
        )

    try:
        path = resolve_under_shared(path_value)
    except Exception as exc:
        return _validation._google_error("google_drive_upload_file", "invalid_path", exc, started)

    if not path.exists() or not path.is_file():
        return err(
            "google_drive_upload_file",
            "file_not_found",
            f"file not found: {path}",
            "google",
            started,
        )

    upload_name = file_name or path.name
    if mime_type and not _validation._MIME_TYPE_RE.match(mime_type):
        return err("google_drive_upload_file", "invalid_mime_type", f"invalid mime_type: {mime_type}", "google", started)
    upload_mime = mime_type or mimetypes.guess_type(upload_name)[0] or "application/octet-stream"
    metadata: dict[str, Any] = {"name": upload_name}
    if parent_folder_id:
        metadata["parents"] = [parent_folder_id]
    if convert_to:
        metadata["mimeType"] = _CONVERT_TARGETS[convert_to]

    try:
        from googleapiclient.http import MediaFileUpload

        service = _auth._build_service("drive", "v3", _capabilities.DRIVE_WRITE_SCOPES)
        media = MediaFileUpload(str(path), mimetype=upload_mime, resumable=False)
        payload = (
            service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id,name,mimeType,size,parents,webViewLink,webContentLink",
            )
            .execute()
        )
    except Exception as exc:
        return _validation._google_error("google_drive_upload_file", "drive_upload_failed", exc, started)

    return ok(
        "google_drive_upload_file",
        {
            "id": payload.get("id"),
            "name": payload.get("name", upload_name),
            "mime_type": payload.get("mimeType", upload_mime),
            "size": payload.get("size"),
            "parent_folder_id": parent_folder_id,
            "converted_to": convert_to,
            "source_path": str(path),
            "web_view_link": payload.get("webViewLink", ""),
            "web_content_link": payload.get("webContentLink", ""),
        },
        "google",
        started,
    )


def get_tools() -> list[ToolDef]:
    return [
        READ_TOOL(
            name="google_drive_recent_files",
            description="List recently modified Google Drive files.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10, "description": "Maximum files to return (1-50). Defaults to 10."},
                    "query": {"type": "string", "description": "Google Drive search query (e.g. \"name contains 'report'\" or \"mimeType='application/pdf'\")."},
                },
                "required": [],
            },
            handler=_drive_recent_files,
        ),
        WRITE_TOOL(
            name="google_drive_create_folder",
            description="Create a folder in Google Drive.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "folder_name": {"type": "string", "description": "Name for the new folder."},
                    "parent_folder_id": {"type": "string", "description": "Google Drive folder ID to create under. Root if omitted."},
                },
                "required": ["folder_name"],
            },
            handler=_drive_create_folder,
            audit_action="google_drive_create_folder",
        ),
        WRITE_TOOL(
            name="google_drive_create_text_file",
            description="Create a text file directly in Google Drive.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "file_name": {"type": "string", "description": "Name for the new file in Drive."},
                    "content": {"type": "string", "description": "Text content of the file. Defaults to empty."},
                    "parent_folder_id": {"type": "string", "description": "Google Drive folder ID. Root if omitted."},
                    "mime_type": {"type": "string", "description": "MIME type of the file. Defaults to 'text/plain'."},
                },
                "required": ["file_name"],
            },
            handler=_drive_create_text_file,
            audit_action="google_drive_create_text_file",
        ),
        WRITE_TOOL(
            name="google_drive_upload_file",
            description="Upload a file from shared directory to Google Drive, optionally converting it to a Google-native format.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative path of the file to upload."},
                    "file_name": {"type": "string", "description": "Override the filename in Drive. Uses the source filename if omitted."},
                    "parent_folder_id": {"type": "string", "description": "Google Drive folder ID. Root if omitted."},
                    "mime_type": {"type": "string", "description": "Override the MIME type of the uploaded bytes. Auto-detected from extension if omitted."},
                    "convert_to": {
                        "type": "string",
                        "enum": ["presentation", "document", "spreadsheet"],
                        "description": "Convert on upload to a Google-native format: .pptx becomes Google Slides, .docx becomes Google Docs, .xlsx/.csv becomes Google Sheets. Stored as-is if omitted.",
                    },
                },
                "required": ["path"],
            },
            handler=_drive_upload_file,
            audit_action="google_drive_upload_file",
        ),
    ]
