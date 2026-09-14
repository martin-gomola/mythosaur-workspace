from __future__ import annotations

from ..common import PluginSpec, ToolPolicy, plugin_toolset

PLUGIN_ID = "mythosaur.google_workspace"


def _runtime_state(_readonly: bool):
    from .google_tools._capabilities import google_auth_status, google_capabilities

    return google_capabilities(), google_auth_status()


PLUGIN_SPEC = PluginSpec(
    plugin_id=PLUGIN_ID,
    capability_group="google_workspace",
    access_mode="mixed",
    default_category="google_workspace",
    runtime_state=_runtime_state,
    tool_policies={
        "gmail_unread": ToolPolicy(
            required_capability="gmail_read",
            use_when="need raw inbox messages or unread counts for the active account",
            avoid_when="avoid when you need triage structure instead of raw messages",
            success_next=("gmail_send",),
            retryable_error_codes=("gmail_failed", "internal_error"),
        ),
        "gmail_send": ToolPolicy(
            required_capability="gmail_send",
            avoid_when="avoid when the request is read-only or still needs review",
            retryable_error_codes=("gmail_send_failed", "internal_error"),
        ),
        "google_calendar_events": ToolPolicy(
            required_capability="calendar_read",
            use_when="need calendar events in a known time window",
            success_next=("google_calendar_create_event",),
            retryable_error_codes=("calendar_failed", "internal_error"),
        ),
        "google_calendar_create_event": ToolPolicy(
            required_capability="calendar_write",
            use_when="need to create a calendar event after planning is complete",
            avoid_when="avoid when the request is only asking to inspect availability",
            fallback_tools=("google_calendar_events",),
            retryable_error_codes=("calendar_create_failed", "internal_error"),
        ),
        "google_drive_recent_files": ToolPolicy(
            required_capability="drive_read",
            success_next=("google_docs_get", "google_drive_upload_file"),
            retryable_error_codes=("drive_failed", "internal_error"),
        ),
        "google_drive_create_folder": ToolPolicy(
            required_capability="drive_write",
            entity_type="drive_folder",
            retryable_error_codes=("drive_create_failed", "internal_error"),
        ),
        "google_drive_create_text_file": ToolPolicy(
            required_capability="drive_write",
            retryable_error_codes=("drive_create_failed", "internal_error"),
        ),
        "google_drive_upload_file": ToolPolicy(
            required_capability="drive_write",
            retryable_error_codes=("drive_upload_failed", "internal_error"),
        ),
        "google_docs_get": ToolPolicy(
            required_capability="docs_read",
            success_next=("google_docs_create",),
            retryable_error_codes=("docs_failed", "internal_error"),
        ),
        "google_docs_create": ToolPolicy(
            required_capability="docs_write",
            retryable_error_codes=("docs_create_failed", "internal_error"),
        ),
        "google_sheets_read_range": ToolPolicy(required_capability="sheets_read", retryable_error_codes=("sheets_failed", "internal_error")),
        "google_sheets_write_range": ToolPolicy(required_capability="sheets_write", retryable_error_codes=("sheets_write_failed", "internal_error")),
        "google_sheets_append_rows": ToolPolicy(required_capability="sheets_write", retryable_error_codes=("sheets_append_failed", "internal_error")),
        "google_sheets_create_sheet": ToolPolicy(required_capability="sheets_write", retryable_error_codes=("sheets_create_failed", "internal_error")),
        "google_maps_build_route_link": ToolPolicy(required_capability="maps", exposure="advanced"),
        "google_maps_build_place_link": ToolPolicy(required_capability="maps", exposure="advanced"),
        "google_maps_search_places": ToolPolicy(required_capability="maps", retryable_error_codes=("maps_api_failed", "internal_error")),
        "google_maps_compute_route": ToolPolicy(required_capability="maps", retryable_error_codes=("maps_api_failed", "internal_error")),
        "google_photos_list_albums": ToolPolicy(required_capability="photos_read", entity_type="photo_album", retryable_error_codes=("photos_failed", "internal_error")),
        "google_photos_create_album": ToolPolicy(required_capability="photos_write", entity_type="photo_album", retryable_error_codes=("photos_failed", "internal_error")),
        "google_photos_list_media_items": ToolPolicy(required_capability="photos_read", retryable_error_codes=("photos_failed", "internal_error")),
        "google_photos_upload_file": ToolPolicy(required_capability="photos_write", retryable_error_codes=("photos_failed", "internal_error")),
        "google_photos_add_to_album": ToolPolicy(required_capability="photos_write", entity_type="photo_album", retryable_error_codes=("photos_failed", "internal_error")),
        "google_photos_find_duplicate_candidates": ToolPolicy(required_capability="photos_read", exposure="advanced", retryable_error_codes=("photos_failed", "internal_error")),
        "google_photos_create_curated_album": ToolPolicy(required_capability="photos_write", entity_type="photo_album", exposure="advanced", retryable_error_codes=("photos_failed", "internal_error")),
        **{
            name: ToolPolicy(required_capability="notebooklm")
            for name in (
                "notebooklm_auth_status",
                "notebooklm_list_notebooks",
                "notebooklm_query_notebook",
                "notebooklm_create_notebook",
                "notebooklm_list_sources",
                "notebooklm_add_source",
                "notebooklm_create_studio_content",
                "notebooklm_download_artifact",
                "notebooklm_share",
            )
        },
    },
)

READ_TOOL, WRITE_TOOL = plugin_toolset(PLUGIN_SPEC)
