from __future__ import annotations

from typing import Any

import requests

from ...common import (
    ToolDef,
    err,
    listify_strings,
    now_ms,
    ok,
    parse_int,
    resolve_under_shared,
)
from ..google_plugin import READ_TOOL, WRITE_TOOL
from . import _auth, _capabilities, _validation


def _photos_headers(scopes: list[str], *, json_body: bool = True) -> dict[str, str]:
    creds = _auth._get_credentials(scopes)
    headers = {"Authorization": f"Bearer {creds.token}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _photos_request(
    tool_name: str,
    method: str,
    url: str,
    scopes: list[str],
    started: int,
    *,
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
) -> tuple[dict[str, Any] | str | None, dict[str, Any] | None]:
    try:
        request_headers = _photos_headers(scopes, json_body=data is None)
        if headers:
            request_headers.update(headers)
        response = requests.request(
            method,
            url,
            headers=request_headers,
            json=payload if data is None else None,
            params=params,
            data=data,
            timeout=_capabilities._PHOTOS_DEFAULT_TIMEOUT_SEC,
        )
        response.raise_for_status()
    except Exception as exc:
        return None, _validation._google_error(tool_name, "photos_failed", exc, started)

    content_type = (response.headers.get("Content-Type") or "").lower()
    if "application/json" in content_type:
        try:
            return response.json(), None
        except ValueError:
            return None, err(tool_name, "photos_invalid_response", "invalid JSON in API response", "google", started)
    if not response.text:
        return {}, None
    return response.text, None


def _photos_normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("mediaMetadata") or {}
    return {
        "id": item.get("id", ""),
        "description": item.get("description", ""),
        "product_url": item.get("productUrl", ""),
        "base_url": item.get("baseUrl", ""),
        "mime_type": item.get("mimeType", ""),
        "filename": item.get("filename", ""),
        "creation_time": metadata.get("creationTime", ""),
        "width": metadata.get("width"),
        "height": metadata.get("height"),
    }


def _photos_list_media_pages(
    *,
    tool_name: str,
    started: int,
    album_id: str = "",
    max_items: int = 200,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    items: list[dict[str, Any]] = []
    page_token = ""
    remaining = max_items

    while remaining > 0:
        page_size = min(100, remaining)
        if album_id:
            payload: dict[str, Any] = {"albumId": album_id, "pageSize": page_size}
            if page_token:
                payload["pageToken"] = page_token
            response_json, api_error = _photos_request(
                tool_name,
                "POST",
                "https://photoslibrary.googleapis.com/v1/mediaItems:search",
                _capabilities.PHOTOS_READ_SCOPES,
                started,
                payload=payload,
            )
        else:
            params: dict[str, Any] = {"pageSize": page_size}
            if page_token:
                params["pageToken"] = page_token
            response_json, api_error = _photos_request(
                tool_name,
                "GET",
                "https://photoslibrary.googleapis.com/v1/mediaItems",
                _capabilities.PHOTOS_READ_SCOPES,
                started,
                params=params,
            )
        if api_error:
            return None, api_error
        page_items = response_json.get("mediaItems") or []
        items.extend(page_items)
        remaining -= len(page_items)
        page_token = str(response_json.get("nextPageToken") or "").strip()
        if not page_token or not page_items:
            break

    return items, None


def _photos_create_album(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_photos_create_album", "photos_write", started)
    if blocked:
        return blocked

    title = (args.get("title") or "").strip()
    if not title:
        return err("google_photos_create_album", "missing_args", "title is required", "google", started)

    response_json, api_error = _photos_request(
        "google_photos_create_album",
        "POST",
        "https://photoslibrary.googleapis.com/v1/albums",
        _capabilities.PHOTOS_WRITE_SCOPES,
        started,
        payload={"album": {"title": title}},
    )
    if api_error:
        return api_error

    album = response_json.get("album") or response_json
    return ok(
        "google_photos_create_album",
        {
            "id": album.get("id", ""),
            "title": album.get("title", title),
            "product_url": album.get("productUrl", ""),
            "media_items_count": album.get("mediaItemsCount"),
            "cover_photo_base_url": album.get("coverPhotoBaseUrl", ""),
        },
        "google",
        started,
    )


def _photos_list_albums(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_photos_list_albums", "photos_read", started)
    if blocked:
        return blocked

    page_size = parse_int(args.get("page_size"), 20, minimum=1, maximum=50)
    params: dict[str, Any] = {"pageSize": page_size}
    if page_token := (args.get("page_token") or "").strip():
        params["pageToken"] = page_token

    response_json, api_error = _photos_request(
        "google_photos_list_albums",
        "GET",
        "https://photoslibrary.googleapis.com/v1/albums",
        _capabilities.PHOTOS_READ_SCOPES,
        started,
        params=params,
    )
    if api_error:
        return api_error

    albums = []
    for album in response_json.get("albums") or []:
        albums.append(
            {
                "id": album.get("id", ""),
                "title": album.get("title", ""),
                "product_url": album.get("productUrl", ""),
                "media_items_count": album.get("mediaItemsCount"),
                "cover_photo_base_url": album.get("coverPhotoBaseUrl", ""),
            }
        )

    return ok(
        "google_photos_list_albums",
        {"albums": albums, "next_page_token": response_json.get("nextPageToken", "")},
        "google",
        started,
    )


def _photos_list_media_items(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_photos_list_media_items", "photos_read", started)
    if blocked:
        return blocked

    album_id = (args.get("album_id") or "").strip()
    max_items = parse_int(args.get("max_items"), 50, minimum=1, maximum=500)
    items, api_error = _photos_list_media_pages(
        tool_name="google_photos_list_media_items",
        started=started,
        album_id=album_id,
        max_items=max_items,
    )
    if api_error:
        return api_error

    return ok(
        "google_photos_list_media_items",
        {
            "album_id": album_id,
            "items": [_photos_normalize_item(item) for item in items or []],
        },
        "google",
        started,
    )


def _photos_add_to_album(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_photos_add_to_album", "photos_write", started)
    if blocked:
        return blocked

    album_id = (args.get("album_id") or "").strip()
    media_item_ids = listify_strings(args.get("media_item_ids"))
    if not album_id or not media_item_ids:
        return err(
            "google_photos_add_to_album",
            "missing_args",
            "album_id and media_item_ids are required",
            "google",
            started,
        )

    _response_json, api_error = _photos_request(
        "google_photos_add_to_album",
        "POST",
        f"https://photoslibrary.googleapis.com/v1/albums/{album_id}:batchAddMediaItems",
        _capabilities.PHOTOS_WRITE_SCOPES,
        started,
        payload={"mediaItemIds": media_item_ids},
    )
    if api_error:
        return api_error

    return ok(
        "google_photos_add_to_album",
        {"album_id": album_id, "media_item_ids": media_item_ids, "added_count": len(media_item_ids)},
        "google",
        started,
    )


def _photos_upload_file(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_photos_upload_file", "photos_write", started)
    if blocked:
        return blocked

    path = (args.get("path") or "").strip()
    album_id = (args.get("album_id") or "").strip()
    description = (args.get("description") or "").strip()
    if not path:
        return err("google_photos_upload_file", "missing_args", "path is required", "google", started)

    try:
        source_path = resolve_under_shared(path)
    except Exception as exc:
        return _validation._google_error("google_photos_upload_file", "invalid_path", exc, started)
    if not source_path.exists() or not source_path.is_file():
        return err("google_photos_upload_file", "missing_file", f"file not found: {source_path}", "google", started)
    file_size = source_path.stat().st_size
    if file_size > _validation._MAX_UPLOAD_BYTES:
        return err(
            "google_photos_upload_file", "file_too_large",
            f"file is {file_size} bytes, max allowed is {_validation._MAX_UPLOAD_BYTES}",
            "google", started,
        )

    upload_token, api_error = _photos_request(
        "google_photos_upload_file",
        "POST",
        "https://photoslibrary.googleapis.com/v1/uploads",
        _capabilities.PHOTOS_WRITE_SCOPES,
        started,
        headers={
            "Content-Type": "application/octet-stream",
            "X-Goog-Upload-File-Name": source_path.name,
            "X-Goog-Upload-Protocol": "raw",
        },
        data=source_path.read_bytes(),
    )
    if api_error:
        return api_error

    batch_payload: dict[str, Any] = {
        "newMediaItems": [
            {
                "description": description,
                "simpleMediaItem": {"uploadToken": str(upload_token), "fileName": source_path.name},
            }
        ]
    }
    if album_id:
        batch_payload["albumId"] = album_id

    response_json, api_error = _photos_request(
        "google_photos_upload_file",
        "POST",
        "https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate",
        _capabilities.PHOTOS_WRITE_SCOPES,
        started,
        payload=batch_payload,
    )
    if api_error:
        return api_error

    results = response_json.get("newMediaItemResults") or []
    created = []
    for item in results:
        status = item.get("status") or {}
        media_item = item.get("mediaItem") or {}
        created.append(
            {
                "status_code": status.get("code"),
                "status_message": status.get("message", ""),
                "media_item": _photos_normalize_item(media_item) if media_item else {},
            }
        )

    return ok(
        "google_photos_upload_file",
        {
            "source_path": str(source_path),
            "album_id": album_id,
            "results": created,
        },
        "google",
        started,
    )


def _photos_duplicate_key(item: dict[str, Any]) -> str:
    normalized = _photos_normalize_item(item)
    return "|".join(
        [
            normalized.get("filename", "").lower(),
            normalized.get("mime_type", "").lower(),
            str(normalized.get("width") or ""),
            str(normalized.get("height") or ""),
            normalized.get("creation_time", ""),
        ]
    )


def _photos_find_duplicate_candidates(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_photos_find_duplicate_candidates", "photos_read", started)
    if blocked:
        return blocked

    album_id = (args.get("album_id") or "").strip()
    max_items = parse_int(args.get("max_items"), 200, minimum=1, maximum=500)
    items, api_error = _photos_list_media_pages(
        tool_name="google_photos_find_duplicate_candidates",
        started=started,
        album_id=album_id,
        max_items=max_items,
    )
    if api_error:
        return api_error

    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items or []:
        key = _photos_duplicate_key(item)
        groups.setdefault(key, []).append(_photos_normalize_item(item))

    duplicate_groups = [group for group in groups.values() if len(group) > 1]
    duplicate_groups.sort(key=len, reverse=True)

    return ok(
        "google_photos_find_duplicate_candidates",
        {
            "album_id": album_id,
            "duplicate_group_count": len(duplicate_groups),
            "groups": duplicate_groups,
            "notes": [
                "Duplicate detection only covers app-created Google Photos items that the current API can list.",
                "Grouping is heuristic: filename, mime type, dimensions, and creation time.",
            ],
        },
        "google",
        started,
    )


def _photos_create_curated_album(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_photos_create_curated_album", "photos_write", started)
    if blocked:
        return blocked

    title = (args.get("title") or "").strip()
    media_item_ids = listify_strings(args.get("media_item_ids"))
    if not title or not media_item_ids:
        return err(
            "google_photos_create_curated_album",
            "missing_args",
            "title and media_item_ids are required",
            "google",
            started,
        )

    album_result = _photos_create_album({"title": title})
    if album_result.get("status") != "ok":
        return album_result
    album_id = str((album_result.get("data") or {}).get("id") or "")
    add_result = _photos_add_to_album({"album_id": album_id, "media_item_ids": media_item_ids})
    if add_result.get("status") != "ok":
        return add_result

    return ok(
        "google_photos_create_curated_album",
        {
            "album_id": album_id,
            "title": title,
            "media_item_ids": media_item_ids,
            "product_url": (album_result.get("data") or {}).get("product_url", ""),
        },
        "google",
        started,
    )


def get_tools() -> list[ToolDef]:
    return [
        READ_TOOL(
            name="google_photos_list_albums",
            description="List app-created Google Photos albums available to the authorized account.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "page_size": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20, "description": "Albums per page (1-50). Defaults to 20."},
                    "page_token": {"type": "string", "description": "Pagination token from a previous response."},
                },
                "required": [],
            },
            handler=_photos_list_albums,
        ),
        WRITE_TOOL(
            name="google_photos_create_album",
            description="Create an app-created Google Photos album.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"title": {"type": "string", "description": "Title for the new album."}},
                "required": ["title"],
            },
            handler=_photos_create_album,
            audit_action="google_photos_create_album",
        ),
        READ_TOOL(
            name="google_photos_list_media_items",
            description="List app-created Google Photos media items, optionally within an album.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "album_id": {"type": "string", "description": "Filter to items in this album. Lists all items if omitted."},
                    "max_items": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50, "description": "Maximum items to return (1-500). Defaults to 50."},
                },
                "required": [],
            },
            handler=_photos_list_media_items,
        ),
        WRITE_TOOL(
            name="google_photos_upload_file",
            description="Upload a file from shared directory into Google Photos app-created storage, optionally adding it to an album.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative path of the image/video file to upload."},
                    "album_id": {"type": "string", "description": "Album ID to add the uploaded item to."},
                    "description": {"type": "string", "description": "Description/caption for the uploaded media item."},
                },
                "required": ["path"],
            },
            handler=_photos_upload_file,
            audit_action="google_photos_upload_file",
        ),
        WRITE_TOOL(
            name="google_photos_add_to_album",
            description="Add app-created Google Photos media items to an album.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "album_id": {"type": "string", "description": "Album ID to add items to."},
                    "media_item_ids": {"type": "array", "items": {"type": "string"}, "description": "List of media item IDs to add to the album."},
                },
                "required": ["album_id", "media_item_ids"],
            },
            handler=_photos_add_to_album,
            audit_action="google_photos_add_to_album",
        ),
        READ_TOOL(
            name="google_photos_find_duplicate_candidates",
            description="Find likely duplicate app-created Google Photos items using filename and metadata heuristics.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "album_id": {"type": "string", "description": "Scope duplicate search to this album. Searches all items if omitted."},
                    "max_items": {"type": "integer", "minimum": 1, "maximum": 500, "default": 200, "description": "Maximum items to scan for duplicates (1-500). Defaults to 200."},
                },
                "required": [],
            },
            handler=_photos_find_duplicate_candidates,
        ),
        WRITE_TOOL(
            name="google_photos_create_curated_album",
            description="Create a new curated Google Photos album from selected app-created media item ids.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string", "description": "Title for the new curated album."},
                    "media_item_ids": {"type": "array", "items": {"type": "string"}, "description": "Media item IDs to include in the album."},
                },
                "required": ["title", "media_item_ids"],
            },
            handler=_photos_create_curated_album,
            audit_action="google_photos_create_curated_album",
        ),
    ]
