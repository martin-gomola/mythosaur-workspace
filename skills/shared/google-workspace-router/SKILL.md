---
name: google-workspace-router
description: Routes Google Calendar meetings and schedules, Gmail email and replies, Drive, Sheet ranges, Docs, Photos, Maps routes, and NotebookLM research notebooks. Use for Workspace data, NotebookLM context, or available actions.
---

# Google Workspace Router

Route requests to the Google and NotebookLM tools in `mythosaur-workspace`.

## Optional local NotebookLM index

If `references/notebooks.md` exists, use it as a dated routing index for the
user's known NotebookLM notebooks. It contains notebook IDs and topic hints
only; it is not a copy of notebook content or an authority about current
availability. The public source tree includes only
[references/notebooks.md.example](references/notebooks.md.example); copy it to
`notebooks.md` for a local index and never commit that copy.

1. For a clear match, use the indexed notebook ID with
   `notebooklm_query_notebook`.
2. If the user asks for the current list, names an unknown notebook, or the
   match is ambiguous, call `notebooklm_list_notebooks` first and select from
   the returned titles and IDs. Do not guess an ID.
3. Use `notebooklm_list_sources` only when the question needs source-level
   narrowing. Do not load every source by default.
4. Treat NotebookLM output as source-grounded evidence, not unquestionable
   truth. State when the notebook does not cover the question or the live tool
   is unavailable.

The index is a convenience cache. If it conflicts with the live list, trust the
live list and use the new ID for that turn; update the index only through a
deliberate repository change.

## Current Tool Map

**Calendar**
- `google_calendar_events` — list events
- `google_calendar_create_event` — create an event

**Gmail**
- `gmail_unread` — inbox status and recent messages
- `gmail_send` — send a message

**Drive**
- `google_drive_recent_files` — recent files
- `google_drive_create_folder` — create a folder
- `google_drive_create_text_file` — create a text/markdown file
- `google_drive_upload_file` — upload a workspace file, optionally converting it
  on the way in: `convert_to="presentation"` turns a `.pptx` into Google Slides,
  `"document"` a `.docx` into Docs, `"spreadsheet"` a `.xlsx`/`.csv` into Sheets.
  There is no Slides authoring tool; converting an uploaded file is the way to
  put a deck in Slides.

**Sheets**
- `google_sheets_read_range` — read cell ranges
- `google_sheets_write_range` — write cell ranges
- `google_sheets_append_rows` — append rows
- `google_sheets_create_sheet` — create a tab

**Docs**
- `google_docs_get` — read a document
- `google_docs_create` — create a document

**Photos** (app-created items only)
- `google_photos_list_albums` — list albums
- `google_photos_create_album` — create an album
- `google_photos_list_media_items` — list media
- `google_photos_upload_file` — upload a file
- `google_photos_add_to_album` — add media to album
- `google_photos_find_duplicate_candidates` — find duplicates
- `google_photos_create_curated_album` — create curated album

**Maps**
- `google_maps_build_route_link` — build a route link
- `google_maps_build_place_link` — build a place link
- `google_maps_search_places` — search places (requires API key)
- `google_maps_compute_route` — compute route (requires API key)

**NotebookLM**
- `notebooklm_auth_status` — check auth
- `notebooklm_list_notebooks` — list notebooks
- `notebooklm_query_notebook` — grounded Q&A
- `notebooklm_create_notebook` — create a notebook
- `notebooklm_list_sources` — list sources in a notebook
- `notebooklm_add_source` — add URL, text, Drive, or file source
- `notebooklm_create_studio_content` — generate podcast, video, mind map, slides, etc.
- `notebooklm_download_artifact` — download generated content
- `notebooklm_share` — share notebook publicly or via invite

## Routing Rules

1. Match the request to the narrowest tool above. Prefer read tools before write tools.
2. For inbox or Gmail triage, use `action-triage` when available. Otherwise sort items into urgent, reply-needed, and monitor-only groups before any send action.
3. For NotebookLM:
   - `notebooklm_list_notebooks` first if the notebook is not clearly identified.
   - `notebooklm_query_notebook` only after you know the target notebook.
   - `notebooklm_create_notebook` + `notebooklm_add_source` to build a knowledge base.
   - `notebooklm_create_studio_content` to generate podcasts, mind maps, slides, etc.
   - `notebooklm_download_artifact` to retrieve generated content.
   - `notebooklm_share` to make notebooks accessible via public or invite link.
4. Do not guess. If the tool does not return the answer, say the data is missing or unavailable.
5. If the user asks for a write action that is not yet implemented, say so clearly instead of improvising.
6. For Docs or Sheets publication workflows, use `evidence-briefing` when available. Otherwise draft and review the content directly before calling the write tool.
7. For Gmail send actions, use `action-triage` when available. Otherwise draft and review the reply directly before calling `gmail_send`.

## Not Yet Available

- Moving or deleting Drive files
- Gmail draft creation
- Full-library duplicate scanning across the user's entire personal Google Photos library

## Standalone Mode

If Google Workspace or NotebookLM execution is unavailable:

- draft the email, calendar entry, note, or response
- state what required API action could not be executed
- gather the fields needed for a later retry or copy-paste completion

Keep the workflow useful even when the execution layer is temporarily unavailable.
