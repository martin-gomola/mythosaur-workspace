from __future__ import annotations

from typing import Any

from ...common import ToolDef, err, now_ms, ok, parse_int
from ..google_plugin import READ_TOOL, WRITE_TOOL
from . import _auth, _capabilities, _validation


def _docs_extract_text(elements: list[dict[str, Any]] | None, chunks: list[str]) -> None:
    for element in elements or []:
        paragraph = element.get("paragraph") or {}
        for part in paragraph.get("elements") or []:
            text_run = (part.get("textRun") or {}).get("content")
            if text_run:
                chunks.append(text_run)

        table = element.get("table") or {}
        for row in table.get("tableRows") or []:
            for cell in row.get("tableCells") or []:
                _docs_extract_text(cell.get("content") or [], chunks)

        table_of_contents = element.get("tableOfContents") or {}
        _docs_extract_text(table_of_contents.get("content") or [], chunks)


def _docs_get(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_docs_get", "docs_read", started)
    if blocked:
        return blocked

    document_id = (args.get("document_id") or "").strip()
    include_text = bool(args.get("include_text", True))
    max_chars = parse_int(args.get("max_chars"), 20000, minimum=100, maximum=200000)
    if not document_id:
        return err("google_docs_get", "missing_args", "document_id is required", "google", started)

    try:
        service = _auth._build_service("docs", "v1", _capabilities.DOCS_SCOPES)
        payload = service.documents().get(documentId=document_id).execute()
    except Exception as exc:
        return _validation._google_error("google_docs_get", "docs_failed", exc, started)

    text = ""
    if include_text:
        chunks: list[str] = []
        body = payload.get("body") or {}
        _docs_extract_text(body.get("content") or [], chunks)
        text = "".join(chunks).strip()
        if len(text) > max_chars:
            text = text[:max_chars]

    return ok(
        "google_docs_get",
        {
            "document_id": payload.get("documentId", document_id),
            "title": payload.get("title", ""),
            "revision_id": payload.get("revisionId", ""),
            "document_url": f"https://docs.google.com/document/d/{payload.get('documentId', document_id)}/edit",
            "text": text,
            "truncated": include_text and len(text) == max_chars,
        },
        "google",
        started,
    )


def _docs_create(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("google_docs_create", "docs_write", started)
    if blocked:
        return blocked

    title = (args.get("title") or "").strip()
    content = args.get("content")
    if not title:
        return err("google_docs_create", "missing_args", "title is required", "google", started)
    if content is None:
        content = ""
    if not isinstance(content, str):
        return err("google_docs_create", "invalid_content", "content must be a string", "google", started)
    size_err = _validation._validate_content_size("google_docs_create", content, _validation._MAX_CONTENT_BYTES, started)
    if size_err:
        return size_err

    try:
        service = _auth._build_service("docs", "v1", _capabilities.DOCS_WRITE_SCOPES)
        payload = service.documents().create(body={"title": title}).execute()
        document_id = payload.get("documentId", "")
        if content and document_id:
            service.documents().batchUpdate(
                documentId=document_id,
                body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
            ).execute()
    except Exception as exc:
        return _validation._google_error("google_docs_create", "docs_create_failed", exc, started)

    return ok(
        "google_docs_create",
        {
            "document_id": payload.get("documentId", ""),
            "title": payload.get("title", title),
            "revision_id": payload.get("revisionId", ""),
            "document_url": f"https://docs.google.com/document/d/{payload.get('documentId', '')}/edit",
            "content_chars": len(content),
        },
        "google",
        started,
    )


def get_tools() -> list[ToolDef]:
    return [
        READ_TOOL(
            name="google_docs_get",
            description="Read a Google Docs document and optionally return plain text content.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "document_id": {"type": "string", "description": "Google Docs document ID (from the URL)."},
                    "include_text": {"type": "boolean", "description": "Return plain text content of the document. Defaults to true."},
                    "max_chars": {"type": "integer", "minimum": 100, "maximum": 200000, "default": 20000, "description": "Maximum text characters to return (100-200000). Defaults to 20000."},
                },
                "required": ["document_id"],
            },
            handler=_docs_get,
        ),
        WRITE_TOOL(
            name="google_docs_create",
            description="Create a Google Docs document with optional initial text content.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string", "description": "Title for the new Google Doc."},
                    "content": {"type": "string", "description": "Optional initial text content for the document."},
                },
                "required": ["title"],
            },
            handler=_docs_create,
            audit_action="google_docs_create",
        ),
    ]
