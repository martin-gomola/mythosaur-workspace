from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any

from ...common import ToolDef, err, listify_strings, now_ms, ok, parse_int
from ..google_plugin import READ_TOOL, WRITE_TOOL
from . import _auth, _capabilities, _validation


def _gmail_unread(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("gmail_unread", "gmail_read", started)
    if blocked:
        return blocked
    max_results = parse_int(args.get("max_results"), 10, minimum=1, maximum=50)
    include_snippets = bool(args.get("include_snippets", False))
    unread_only = bool(args.get("unread_only", False))
    label_ids = list(args.get("label_ids") or ["INBOX"])
    if len(label_ids) > _validation._MAX_LABEL_IDS:
        return err("gmail_unread", "too_many_labels", f"max {_validation._MAX_LABEL_IDS} label_ids allowed", "google", started)
    if unread_only and "UNREAD" not in label_ids:
        label_ids.append("UNREAD")

    try:
        service = _auth._build_service("gmail", "v1", _capabilities.GMAIL_SCOPES)
        list_payload = service.users().messages().list(userId="me", labelIds=label_ids, maxResults=max_results).execute()
        unread_label_ids = label_ids if "UNREAD" in label_ids else [*label_ids, "UNREAD"]
        unread_payload = service.users().messages().list(userId="me", labelIds=unread_label_ids, maxResults=1).execute()
    except Exception as exc:
        return _validation._google_error("gmail_unread", "gmail_failed", exc, started)

    messages = []
    for item in list_payload.get("messages") or []:
        detail = service.users().messages().get(
            userId="me",
            id=item["id"],
            format="metadata",
            metadataHeaders=["Subject", "From", "Date"],
        ).execute()
        headers = {header["name"].lower(): header["value"] for header in detail.get("payload", {}).get("headers", [])}
        row = {
            "id": item["id"],
            "thread_id": detail.get("threadId", ""),
            "subject": headers.get("subject", ""),
            "from": headers.get("from", ""),
            "date": headers.get("date", ""),
            "label_ids": detail.get("labelIds") or [],
            "is_unread": "UNREAD" in (detail.get("labelIds") or []),
        }
        if include_snippets:
            row["snippet"] = detail.get("snippet", "")
        messages.append(row)

    return ok(
        "gmail_unread",
        {
            "message_count": list_payload.get("resultSizeEstimate", len(messages)),
            "unread_count": unread_payload.get(
                "resultSizeEstimate",
                sum(1 for message in messages if message["is_unread"]),
            ),
            "messages": messages,
        },
        "google",
        started,
    )


def _gmail_send(args: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    blocked = _capabilities._capability_guard("gmail_send", "gmail_send", started)
    if blocked:
        return blocked
    to = listify_strings(args.get("to"))
    cc = listify_strings(args.get("cc"))
    bcc = listify_strings(args.get("bcc"))
    subject = (args.get("subject") or "").strip()
    body_text = str(args.get("body_text") or "").strip()
    body_html = str(args.get("body_html") or "").strip()

    if not to or not subject or (not body_text and not body_html):
        return err(
            "gmail_send",
            "missing_args",
            "to, subject, and either body_text or body_html are required",
            "google",
            started,
        )

    for field, addrs in [("to", to), ("cc", cc), ("bcc", bcc)]:
        if addrs:
            email_err = _validation._validate_emails("gmail_send", field, addrs, started)
            if email_err:
                return email_err

    combined_size = len(body_text.encode("utf-8")) + len(body_html.encode("utf-8"))
    if combined_size > _validation._MAX_CONTENT_BYTES:
        return err(
            "gmail_send", "content_too_large",
            f"body is {combined_size} bytes, max allowed is {_validation._MAX_CONTENT_BYTES}",
            "google", started,
        )

    if body_html and _validation._HTML_DANGEROUS_RE.search(body_html):
        return err(
            "gmail_send", "unsafe_html",
            "body_html contains disallowed content (script, iframe, event handlers)",
            "google", started,
        )

    message = EmailMessage()
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    message["Subject"] = subject

    if body_text:
        message.set_content(body_text)
        if body_html:
            message.add_alternative(body_html, subtype="html")
    else:
        message.set_content(body_html, subtype="html")

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    try:
        service = _auth._build_service("gmail", "v1", _capabilities.GMAIL_SEND_SCOPES)
        payload = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    except Exception as exc:
        return _validation._google_error("gmail_send", "gmail_send_failed", exc, started)

    return ok(
        "gmail_send",
        {
            "id": payload.get("id"),
            "thread_id": payload.get("threadId", ""),
            "label_ids": payload.get("labelIds") or [],
            "to": to,
            "cc": cc,
            "bcc_count": len(bcc),
            "subject": subject,
        },
        "google",
        started,
    )


def get_tools() -> list[ToolDef]:
    return [
        READ_TOOL(
            name="gmail_unread",
            description="Return recent Gmail inbox messages for the active account, including unread status.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10, "description": "Maximum messages to return (1-50). Defaults to 10."},
                    "include_snippets": {"type": "boolean", "description": "Include message snippet previews in results. Defaults to false."},
                    "unread_only": {"type": "boolean", "description": "Return only unread messages. Defaults to false."},
                    "label_ids": {"type": "array", "items": {"type": "string"}, "description": "Gmail label IDs to filter by. Defaults to ['INBOX']."},
                },
                "required": [],
            },
            handler=_gmail_unread,
        ),
        WRITE_TOOL(
            name="gmail_send",
            description="Send a Gmail message from the active account.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "to": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                        "description": "Recipient email address(es). Single string or array of strings.",
                    },
                    "cc": {"type": "array", "items": {"type": "string"}, "description": "CC recipient email addresses."},
                    "bcc": {"type": "array", "items": {"type": "string"}, "description": "BCC recipient email addresses."},
                    "subject": {"type": "string", "description": "Email subject line."},
                    "body_text": {"type": "string", "description": "Plain text email body. Provide body_text and/or body_html."},
                    "body_html": {"type": "string", "description": "HTML email body. Scripts, iframes, and event handlers are rejected."},
                },
                "required": ["to", "subject"],
            },
            handler=_gmail_send,
            audit_action="gmail_send",
        ),
    ]
