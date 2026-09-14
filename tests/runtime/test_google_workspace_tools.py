import sys
import types

import pytest

from services.mcp_server.plugins.workspace.google_tools import _auth as auth
from services.mcp_server.plugins.workspace.google_tools import _calendar as cal
from services.mcp_server.plugins.workspace.google_tools import _capabilities as caps
from services.mcp_server.plugins.workspace.google_tools import _gmail as gmail
from services.mcp_server.plugins.workspace.google_tools import _drive as drive
from services.mcp_server.plugins.workspace.google_tools import _sheets as sheets
from services.mcp_server.plugins.workspace.google_tools import _docs as docs
from services.mcp_server.plugins.workspace.google_tools import _photos as photos
from services.mcp_server.plugins.workspace.google_tools import _maps as maps


class _CalendarList:
    def execute(self):
        return {
            "items": [
                {
                    "id": "evt1",
                    "summary": "Sync",
                    "start": {"dateTime": "2026-03-06T10:00:00Z"},
                    "end": {"dateTime": "2026-03-06T11:00:00Z"},
                }
            ]
        }


class _CalendarInsert:
    def execute(self):
        return {
            "id": "evt2",
            "summary": "Daily Briefing",
            "start": {"dateTime": "2026-03-09T08:00:00Z"},
            "end": {"dateTime": "2026-03-09T08:15:00Z"},
            "htmlLink": "https://calendar.google.com/event?eid=evt2",
            "attendees": [{"email": "team@example.com"}],  # pii:allow - RFC 2606 test fixture
        }


class _CalendarEvents:
    def list(self, **kwargs):
        return _CalendarList()

    def insert(self, **kwargs):
        return _CalendarInsert()


class _CalendarService:
    def events(self):
        return _CalendarEvents()


class _GmailGet:
    def __init__(self, message_id):
        self.message_id = message_id

    def execute(self):
        if self.message_id == "msg1":
            return {
                "threadId": "thr1",
                "labelIds": ["INBOX", "UNREAD"],
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Demo"},
                        {"name": "From", "value": "team@example.com"},  # pii:allow - RFC 2606 test fixture
                        {"name": "Date", "value": "Fri, 6 Mar 2026 10:00:00 +0000"},
                    ]
                },
                "snippet": "hello",
            }
        return {
            "threadId": "thr2",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Roadmap"},
                    {"name": "From", "value": "product@example.com"},  # pii:allow - RFC 2606 test fixture
                    {"name": "Date", "value": "Fri, 6 Mar 2026 09:00:00 +0000"},
                ]
            },
            "snippet": "plan",
        }


class _GmailSend:
    def execute(self):
        return {"id": "sent1", "threadId": "thr2", "labelIds": ["SENT"]}


class _GmailMessages:
    def list(self, **kwargs):
        label_ids = kwargs.get("labelIds") or []

        class _Result:
            def execute(self_nonlocal):
                if "UNREAD" in label_ids:
                    return {"resultSizeEstimate": 1, "messages": [{"id": "msg1"}]}
                return {"resultSizeEstimate": 2, "messages": [{"id": "msg1"}, {"id": "msg2"}]}

        return _Result()

    def get(self, **kwargs):
        return _GmailGet(kwargs["id"])

    def send(self, **kwargs):
        return _GmailSend()


class _GmailUsers:
    def messages(self):
        return _GmailMessages()


class _GmailService:
    def users(self):
        return _GmailUsers()


class _DriveList:
    def execute(self):
        return {"files": [{"id": "file1", "name": "Roadmap"}]}


class _DriveCreate:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _DriveFiles:
    def list(self, **kwargs):
        return _DriveList()

    def create(self, **kwargs):
        body = kwargs.get("body") or {}
        if body.get("mimeType") == "application/vnd.google-apps.folder":
            return _DriveCreate(
                {
                    "id": "folder1",
                    "name": body.get("name", ""),
                    "mimeType": body.get("mimeType", ""),
                    "webViewLink": "https://drive.google.com/folder1",
                }
            )
        return _DriveCreate(
            {
                "id": "upload1",
                "name": body.get("name", ""),
                "mimeType": "text/plain",
                "size": "12",
                "webViewLink": "https://drive.google.com/file1",
                "webContentLink": "https://drive.google.com/download/file1",
            }
        )


class _DriveService:
    def files(self):
        return _DriveFiles()


class _SheetsGet:
    def execute(self):
        return {"majorDimension": "ROWS", "values": [["A1", "B1"]]}


class _SheetsUpdate:
    def execute(self):
        return {"updatedRange": "Sheet1!A1:B1", "updatedRows": 1, "updatedColumns": 2, "updatedCells": 2}


class _SheetsAppend:
    def execute(self):
        return {
            "tableRange": "Sheet1!A1:B1",
            "updates": {"updatedRange": "Sheet1!A2:B2", "updatedRows": 1, "updatedColumns": 2, "updatedCells": 2},
        }


class _SheetsValues:
    def get(self, **kwargs):
        return _SheetsGet()

    def update(self, **kwargs):
        return _SheetsUpdate()

    def append(self, **kwargs):
        return _SheetsAppend()


class _SheetsBatchUpdate:
    def execute(self):
        return {"replies": [{"addSheet": {"properties": {"sheetId": 99, "title": "Routes", "index": 1}}}]}


class _SheetsSpreadsheets:
    def values(self):
        return _SheetsValues()

    def batchUpdate(self, **kwargs):
        return _SheetsBatchUpdate()


class _SheetsService:
    def spreadsheets(self):
        return _SheetsSpreadsheets()


class _DocsGet:
    def execute(self):
        return {
            "documentId": "doc1",
            "title": "Ops Notes",
            "revisionId": "rev1",
            "body": {
                "content": [
                    {"paragraph": {"elements": [{"textRun": {"content": "Line one.\n"}}]}},
                    {"paragraph": {"elements": [{"textRun": {"content": "Line two.\n"}}]}},
                ]
            },
        }


class _DocsCreate:
    def execute(self):
        return {"documentId": "doc2", "title": "Daily Briefing", "revisionId": "rev2"}


class _DocsBatchUpdate:
    def execute(self):
        return {"replies": []}


class _DocsDocuments:
    def get(self, **kwargs):
        return _DocsGet()

    def create(self, **kwargs):
        return _DocsCreate()

    def batchUpdate(self, **kwargs):
        return _DocsBatchUpdate()


class _DocsService:
    def documents(self):
        return _DocsDocuments()


class _MediaFileUpload:
    def __init__(self, filename, mimetype=None, resumable=False):
        self.filename = filename
        self.mimetype = mimetype
        self.resumable = resumable


class _MediaInMemoryUpload:
    def __init__(self, body, mimetype=None, resumable=False):
        self.body = body
        self.mimetype = mimetype
        self.resumable = resumable


class _FakeCreds:
    token = "photos-token"


class _MapsResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text or ""

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests as _req
            error = _req.HTTPError(self.text or "maps error")
            error.response = self
            raise error

    def json(self):
        return self._payload


class _HTTPResponse:
    def __init__(self, payload=None, *, status_code=200, text="", headers=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text
        self.headers = headers or {"Content-Type": "application/json"}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests as _req
            error = _req.HTTPError(self.text or "http error")
            error.response = self
            raise error

    def json(self):
        if self._payload is None:
            raise ValueError("no json payload")
        return self._payload


def test_google_calendar_events(monkeypatch):
    monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _CalendarService())
    result = cal._calendar_events(
        {"time_min": "2026-03-06T00:00:00Z", "time_max": "2026-03-07T00:00:00Z"}
    )
    assert result["status"] == "ok"
    assert result["data"]["events"][0]["summary"] == "Sync"


def test_google_calendar_create_event(monkeypatch):
    monkeypatch.setenv("MW_GOOGLE_CALENDAR_WRITE_ENABLED", "true")
    monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _CalendarService())
    result = cal._calendar_create_event(
        {
            "summary": "Daily Briefing",
            "start_time": "2026-03-09T08:00:00Z",
            "end_time": "2026-03-09T08:15:00Z",
            "attendees": ["team@example.com"],  # pii:allow - RFC 2606 test fixture
        }
    )
    assert result["status"] == "ok"
    assert result["data"]["id"] == "evt2"
    assert result["data"]["summary"] == "Daily Briefing"


def test_gmail_unread(monkeypatch):
    monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _GmailService())
    result = gmail._gmail_unread({"max_results": 5, "include_snippets": True})
    assert result["status"] == "ok"
    assert result["data"]["unread_count"] == 1
    assert result["data"]["message_count"] == 2
    assert result["data"]["messages"][0]["subject"] == "Demo"
    assert result["data"]["messages"][0]["is_unread"] is True
    assert result["data"]["messages"][1]["subject"] == "Roadmap"
    assert result["data"]["messages"][1]["is_unread"] is False


def test_gmail_unread_only(monkeypatch):
    monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _GmailService())
    result = gmail._gmail_unread({"max_results": 5, "unread_only": True})
    assert result["status"] == "ok"
    assert result["data"]["unread_count"] == 1
    assert result["data"]["message_count"] == 1
    assert len(result["data"]["messages"]) == 1
    assert result["data"]["messages"][0]["subject"] == "Demo"


def test_gmail_send(monkeypatch):
    monkeypatch.setenv("MW_GOOGLE_GMAIL_SEND_ENABLED", "true")
    monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _GmailService())
    result = gmail._gmail_send(
        {"to": ["person@example.com"], "subject": "Hello", "body_text": "Plain text body"}  # pii:allow - RFC 2606 test fixture
    )
    assert result["status"] == "ok"
    assert result["data"]["id"] == "sent1"
    assert result["data"]["subject"] == "Hello"


def test_google_drive_recent_files(monkeypatch):
    monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _DriveService())
    result = drive._drive_recent_files({"max_results": 5})
    assert result["status"] == "ok"
    assert result["data"]["files"][0]["name"] == "Roadmap"


def test_google_drive_create_folder(monkeypatch):
    monkeypatch.setenv("MW_GOOGLE_DRIVE_WRITE_ENABLED", "true")
    monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _DriveService())
    result = drive._drive_create_folder({"folder_name": "Routes"})
    assert result["status"] == "ok"
    assert result["data"]["id"] == "folder1"
    assert result["data"]["name"] == "Routes"


def test_google_drive_upload_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MW_GOOGLE_DRIVE_WRITE_ENABLED", "true")
    monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _DriveService())
    monkeypatch.setenv("MW_SHARED_ROOT", str(tmp_path))
    monkeypatch.setitem(sys.modules, "googleapiclient", types.SimpleNamespace(http=types.SimpleNamespace()))
    monkeypatch.setitem(sys.modules, "googleapiclient.http", types.SimpleNamespace(MediaFileUpload=_MediaFileUpload))
    sample = tmp_path / "sample.txt"
    sample.write_text("hello world", encoding="utf-8")

    result = drive._drive_upload_file({"path": "sample.txt"})

    assert result["status"] == "ok"
    assert result["data"]["id"] == "upload1"
    assert result["data"]["source_path"] == str(sample)
    assert result["data"]["converted_to"] == ""


def test_google_drive_upload_file_converts_to_slides(monkeypatch, tmp_path):
    monkeypatch.setenv("MW_GOOGLE_DRIVE_WRITE_ENABLED", "true")
    monkeypatch.setenv("MW_SHARED_ROOT", str(tmp_path))
    monkeypatch.setitem(sys.modules, "googleapiclient", types.SimpleNamespace(http=types.SimpleNamespace()))
    monkeypatch.setitem(sys.modules, "googleapiclient.http", types.SimpleNamespace(MediaFileUpload=_MediaFileUpload))

    bodies: list[dict] = []

    class _RecordingFiles(_DriveFiles):
        def create(self, **kwargs):
            bodies.append(kwargs.get("body") or {})
            return super().create(**kwargs)

    class _RecordingService:
        def files(self):
            return _RecordingFiles()

    monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _RecordingService())

    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"PK\x03\x04fake pptx")

    result = drive._drive_upload_file({"path": "deck.pptx", "convert_to": "presentation"})

    assert result["status"] == "ok"
    assert result["data"]["converted_to"] == "presentation"
    # Drive only converts when the target type is on the file metadata
    assert bodies[0]["mimeType"] == "application/vnd.google-apps.presentation"


def test_google_drive_upload_file_rejects_unknown_convert_target(monkeypatch, tmp_path):
    monkeypatch.setenv("MW_GOOGLE_DRIVE_WRITE_ENABLED", "true")
    monkeypatch.setenv("MW_SHARED_ROOT", str(tmp_path))
    monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _DriveService())

    result = drive._drive_upload_file({"path": "sample.txt", "convert_to": "slideshow"})

    assert result["status"] == "error"
    assert result["error"]["code"] == "invalid_convert_to"


def test_google_drive_create_text_file(monkeypatch):
    monkeypatch.setenv("MW_GOOGLE_DRIVE_WRITE_ENABLED", "true")
    monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _DriveService())
    monkeypatch.setitem(sys.modules, "googleapiclient", types.SimpleNamespace(http=types.SimpleNamespace()))
    monkeypatch.setitem(
        sys.modules,
        "googleapiclient.http",
        types.SimpleNamespace(MediaInMemoryUpload=_MediaInMemoryUpload),
    )

    result = drive._drive_create_text_file({"file_name": "briefing.md", "content": "# Daily briefing"})

    assert result["status"] == "ok"
    assert result["data"]["id"] == "upload1"
    assert result["data"]["name"] == "briefing.md"
    assert result["data"]["content_bytes"] > 0


def test_google_sheets_read_range(monkeypatch):
    monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _SheetsService())
    result = sheets._sheets_read_range({"spreadsheet_id": "sheet1", "range": "A1:B1"})
    assert result["status"] == "ok"
    assert result["data"]["values"] == [["A1", "B1"]]


def test_google_sheets_write_range(monkeypatch):
    monkeypatch.setenv("MW_GOOGLE_SHEETS_WRITE_ENABLED", "true")
    monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _SheetsService())
    result = sheets._sheets_write_range(
        {"spreadsheet_id": "sheet1", "range": "Sheet1!A1:B1", "values": [["A", "B"]]}
    )
    assert result["status"] == "ok"
    assert result["data"]["updated_cells"] == 2


def test_google_sheets_append_rows(monkeypatch):
    monkeypatch.setenv("MW_GOOGLE_SHEETS_WRITE_ENABLED", "true")
    monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _SheetsService())
    result = sheets._sheets_append_rows(
        {"spreadsheet_id": "sheet1", "range": "Sheet1!A:B", "rows": [["A", "B"]]}
    )
    assert result["status"] == "ok"
    assert result["data"]["updated_rows"] == 1


def test_google_sheets_create_sheet(monkeypatch):
    monkeypatch.setenv("MW_GOOGLE_SHEETS_WRITE_ENABLED", "true")
    monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _SheetsService())
    result = sheets._sheets_create_sheet({"spreadsheet_id": "sheet1", "sheet_title": "Routes"})
    assert result["status"] == "ok"
    assert result["data"]["sheet_id"] == 99
    assert result["data"]["sheet_title"] == "Routes"


def test_google_docs_get(monkeypatch):
    monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _DocsService())
    result = docs._docs_get({"document_id": "doc1"})
    assert result["status"] == "ok"
    assert result["data"]["document_id"] == "doc1"
    assert result["data"]["title"] == "Ops Notes"
    assert "Line one." in result["data"]["text"]


def test_google_docs_create(monkeypatch):
    monkeypatch.setenv("MW_GOOGLE_DOCS_WRITE_ENABLED", "true")
    monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _DocsService())
    result = docs._docs_create({"title": "Daily Briefing", "content": "Status update"})
    assert result["status"] == "ok"
    assert result["data"]["document_id"] == "doc2"
    assert result["data"]["title"] == "Daily Briefing"
    assert result["data"]["content_chars"] == len("Status update")


def test_google_maps_build_route_link():
    result = maps._maps_build_route_link(
        {"origin": "Bratislava", "destination": "Vienna", "waypoints": ["Hainburg"], "travel_mode": "driving"}
    )
    assert result["status"] == "ok"
    assert "google.com/maps/dir/" in result["data"]["url"]
    assert "origin=Bratislava" in result["data"]["url"]


def test_google_maps_build_place_link():
    result = maps._maps_build_place_link({"query": "Bratislava Castle"})
    assert result["status"] == "ok"
    assert "google.com/maps/search/" in result["data"]["url"]
    assert "Bratislava+Castle" in result["data"]["url"]


def test_google_maps_search_places(monkeypatch):
    monkeypatch.setenv("MW_GOOGLE_MAPS_API_KEY", "maps-key")

    def _fake_post(url, json, headers, timeout):
        assert url == "https://places.googleapis.com/v1/places:searchText"
        assert json["textQuery"] == "coffee in Vienna"
        assert headers["X-Goog-Api-Key"] == "maps-key"
        return _MapsResponse(
            {
                "places": [
                    {
                        "id": "place1",
                        "displayName": {"text": "Cafe Central"},
                        "formattedAddress": "Herrengasse 14, Vienna",
                        "googleMapsUri": "https://maps.google.com/?cid=place1",
                        "location": {"latitude": 48.21, "longitude": 16.36},
                        "types": ["cafe", "food"],
                    }
                ]
            }
        )

    monkeypatch.setattr(maps.requests, "post", _fake_post)
    result = maps._maps_search_places({"query": "coffee in Vienna", "max_results": 3})

    assert result["status"] == "ok"
    assert result["data"]["places"][0]["display_name"] == "Cafe Central"
    assert result["data"]["places"][0]["location"]["latitude"] == 48.21


def test_google_maps_compute_route(monkeypatch):
    monkeypatch.setenv("MW_GOOGLE_MAPS_API_KEY", "maps-key")

    def _fake_post(url, json, headers, timeout):
        assert url == "https://routes.googleapis.com/directions/v2:computeRoutes"
        assert json["origin"]["address"] == "Bratislava"
        assert json["destination"]["address"] == "Vienna"
        assert json["travelMode"] == "DRIVE"
        assert headers["X-Goog-Api-Key"] == "maps-key"
        return _MapsResponse(
            {
                "routes": [
                    {
                        "description": "via A4",
                        "distanceMeters": 79000,
                        "duration": "4800s",
                        "polyline": {"encodedPolyline": "abcd"},
                        "legs": [
                            {
                                "distanceMeters": 79000,
                                "duration": "4800s",
                                "steps": [
                                    {"navigationInstruction": {"instructions": "Head north"}},
                                    {"navigationInstruction": {"instructions": "Merge onto A4"}},
                                ],
                            }
                        ],
                    }
                ]
            }
        )

    monkeypatch.setattr(maps.requests, "post", _fake_post)
    result = maps._maps_compute_route({"origin": "Bratislava", "destination": "Vienna"})

    assert result["status"] == "ok"
    assert result["data"]["routes"][0]["distance_meters"] == 79000
    assert result["data"]["routes"][0]["legs"][0]["steps"][0] == "Head north"
    assert "google.com/maps/dir/" in result["data"]["route_link"]


def test_google_maps_api_tools_require_key(monkeypatch):
    monkeypatch.delenv("MW_GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("MW_GOOGLE_MAPS_PLATFORM", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_PLATFORM", raising=False)

    result = maps._maps_search_places({"query": "coffee"})

    assert result["status"] == "error"
    assert result["error"]["code"] == "maps_api_key_missing"


def test_google_maps_accepts_legacy_key_and_referrer_names(monkeypatch):
    monkeypatch.delenv("MW_GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("MW_GOOGLE_MAPS_REFERER", raising=False)
    monkeypatch.delenv("MW_GOOGLE_MAPS_PLATFORM", raising=False)
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "maps-key")
    monkeypatch.setenv("GOOGLE_MAPS_REFERER", "https://maps.example")

    def _fake_post(url, json, headers, timeout):
        assert headers["X-Goog-Api-Key"] == "maps-key"
        assert headers["Referer"] == "https://maps.example"
        return _MapsResponse({"places": []})

    monkeypatch.setattr(maps.requests, "post", _fake_post)

    result = maps._maps_search_places({"query": "coffee"})

    assert result["status"] == "ok"


def test_google_auth_status_includes_maps_service_check(monkeypatch, tmp_path):
    monkeypatch.setenv("MW_GOOGLE_TOKEN_FILE", str(tmp_path / "missing-token.json"))
    monkeypatch.setenv("MW_GOOGLE_MAPS_API_KEY", "maps-key")

    result = auth.google_auth_status()

    assert result["token_present"] is False
    assert result["service_checks"]["maps"]["auth_type"] == "api_key"
    assert result["service_checks"]["maps"]["configured"] is True
    assert result["service_checks"]["maps"]["missing_config"] == []


def test_google_capabilities_auth_status_reports_scope_checks(monkeypatch, tmp_path):
    token_file = tmp_path / "google-token.json"
    token_file.write_text(
        '{"scope": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/calendar.events"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("MW_GOOGLE_TOKEN_FILE", str(token_file))
    monkeypatch.delenv("MW_GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("MW_GOOGLE_MAPS_PLATFORM", raising=False)

    result = caps.google_auth_status()

    assert result["configured"] is True
    assert result["scope_checks"]["gmail_read"]["granted"] is True
    assert result["scope_checks"]["gmail_send"]["granted"] is False
    assert result["service_checks"]["maps"]["configured"] is False


def test_google_photos_create_album(monkeypatch):
    monkeypatch.setenv("MW_GOOGLE_PHOTOS_WRITE_ENABLED", "true")
    monkeypatch.setattr(auth, "_get_credentials", lambda scopes: _FakeCreds())

    def _fake_request(method, url, headers=None, json=None, params=None, data=None, timeout=None):
        assert method == "POST"
        assert url == "https://photoslibrary.googleapis.com/v1/albums"
        assert json == {"album": {"title": "Trip 2026"}}
        assert headers["Authorization"] == "Bearer photos-token"
        return _HTTPResponse({"id": "album1", "title": "Trip 2026", "productUrl": "https://photos.google.com/lr/album1"})

    monkeypatch.setattr(photos.requests, "request", _fake_request)
    result = photos._photos_create_album({"title": "Trip 2026"})

    assert result["status"] == "ok"
    assert result["data"]["id"] == "album1"


def test_google_photos_list_media_items(monkeypatch):
    monkeypatch.setenv("MW_GOOGLE_PHOTOS_READ_ENABLED", "true")
    monkeypatch.setattr(auth, "_get_credentials", lambda scopes: _FakeCreds())

    def _fake_request(method, url, headers=None, json=None, params=None, data=None, timeout=None):
        assert method == "GET"
        assert url == "https://photoslibrary.googleapis.com/v1/mediaItems"
        return _HTTPResponse(
            {
                "mediaItems": [
                    {
                        "id": "media1",
                        "filename": "IMG_001.jpg",
                        "mimeType": "image/jpeg",
                        "mediaMetadata": {
                            "creationTime": "2026-03-01T10:00:00Z",
                            "width": "100",
                            "height": "200",
                        },
                    }
                ]
            }
        )

    monkeypatch.setattr(photos.requests, "request", _fake_request)
    result = photos._photos_list_media_items({"max_items": 5})

    assert result["status"] == "ok"
    assert result["data"]["items"][0]["id"] == "media1"


def test_google_photos_find_duplicate_candidates(monkeypatch):
    monkeypatch.setenv("MW_GOOGLE_PHOTOS_READ_ENABLED", "true")
    monkeypatch.setattr(auth, "_get_credentials", lambda scopes: _FakeCreds())

    def _fake_request(method, url, headers=None, json=None, params=None, data=None, timeout=None):
        return _HTTPResponse(
            {
                "mediaItems": [
                    {
                        "id": "media1",
                        "filename": "IMG_001.jpg",
                        "mimeType": "image/jpeg",
                        "mediaMetadata": {
                            "creationTime": "2026-03-01T10:00:00Z",
                            "width": "100",
                            "height": "200",
                        },
                    },
                    {
                        "id": "media2",
                        "filename": "IMG_001.jpg",
                        "mimeType": "image/jpeg",
                        "mediaMetadata": {
                            "creationTime": "2026-03-01T10:00:00Z",
                            "width": "100",
                            "height": "200",
                        },
                    },
                ]
            }
        )

    monkeypatch.setattr(photos.requests, "request", _fake_request)
    result = photos._photos_find_duplicate_candidates({"max_items": 10})

    assert result["status"] == "ok"
    assert result["data"]["duplicate_group_count"] == 1
    assert len(result["data"]["groups"][0]) == 2


def test_google_photos_upload_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MW_GOOGLE_PHOTOS_WRITE_ENABLED", "true")
    monkeypatch.setenv("MW_SHARED_ROOT", str(tmp_path))
    monkeypatch.setattr(auth, "_get_credentials", lambda scopes: _FakeCreds())

    sample = tmp_path / "photo.jpg"
    sample.write_bytes(b"jpeg-bytes")
    calls = []

    def _fake_request(method, url, headers=None, json=None, params=None, data=None, timeout=None):
        calls.append((method, url, headers, json, data))
        if url.endswith("/uploads"):
            return _HTTPResponse(payload=None, text="upload-token-1", headers={"Content-Type": "text/plain"})
        if url.endswith("/mediaItems:batchCreate"):
            return _HTTPResponse(
                {
                    "newMediaItemResults": [
                        {
                            "status": {"code": 0},
                            "mediaItem": {
                                "id": "media1",
                                "filename": "photo.jpg",
                                "mimeType": "image/jpeg",
                                "mediaMetadata": {
                                    "creationTime": "2026-03-01T10:00:00Z",
                                    "width": "100",
                                    "height": "200",
                                },
                            },
                        }
                    ]
                }
            )
        raise AssertionError(url)

    monkeypatch.setattr(photos.requests, "request", _fake_request)
    result = photos._photos_upload_file({"path": "photo.jpg", "album_id": "album1"})

    assert result["status"] == "ok"
    assert result["data"]["results"][0]["media_item"]["id"] == "media1"
    assert calls[0][1] == "https://photoslibrary.googleapis.com/v1/uploads"
    assert calls[1][1] == "https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate"


def test_google_photos_create_curated_album(monkeypatch):
    monkeypatch.setenv("MW_GOOGLE_PHOTOS_WRITE_ENABLED", "true")
    monkeypatch.setattr(auth, "_get_credentials", lambda scopes: _FakeCreds())
    calls = []

    def _fake_request(method, url, headers=None, json=None, params=None, data=None, timeout=None):
        calls.append((method, url, json))
        if url.endswith("/v1/albums"):
            return _HTTPResponse({"id": "album2", "title": "Favorites"})
        if url.endswith("/albums/album2:batchAddMediaItems"):
            return _HTTPResponse({})
        raise AssertionError(url)

    monkeypatch.setattr(photos.requests, "request", _fake_request)
    result = photos._photos_create_curated_album({"title": "Favorites", "media_item_ids": ["m1", "m2"]})

    assert result["status"] == "ok"
    assert result["data"]["album_id"] == "album2"
    assert calls[1][1].endswith("/albums/album2:batchAddMediaItems")


def test_google_capability_guard(monkeypatch):
    monkeypatch.setenv("MW_GOOGLE_GMAIL_SEND_ENABLED", "false")
    result = gmail._gmail_send(
        {"to": ["person@example.com"], "subject": "Hello", "body_text": "Plain text body"}  # pii:allow - RFC 2606 test fixture
    )
    assert result["status"] == "error"
    assert result["error"]["code"] == "capability_disabled"


@pytest.mark.parametrize(
    ("setup", "call", "error_code"),
    [
        (
            lambda monkeypatch: monkeypatch.setenv("MW_GOOGLE_GMAIL_SEND_ENABLED", "true"),
            lambda: gmail._gmail_send({"to": ["not-an-email"], "subject": "Hello", "body_text": "test"}),
            "invalid_email",
        ),
        (
            lambda monkeypatch: (
                monkeypatch.setenv("MW_GOOGLE_GMAIL_SEND_ENABLED", "true"),
                monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _GmailService()),
            ),
            lambda: gmail._gmail_send(
                {
                    "to": ["person@example.com"],  # pii:allow - RFC 2606 test fixture
                    "subject": "Hello",
                    "body_html": '<div><script>alert("xss")</script></div>',
                }
            ),
            "unsafe_html",
        ),
        (
            lambda monkeypatch: None,
            lambda: cal._calendar_events({"time_min": "not-a-date", "time_max": "2026-03-07T00:00:00Z"}),
            "invalid_timestamp",
        ),
        (
            lambda monkeypatch: monkeypatch.setenv("MW_GOOGLE_CALENDAR_WRITE_ENABLED", "true"),
            lambda: cal._calendar_create_event(
                {
                    "summary": "Test",
                    "start_time": "2026-03-09T08:00:00Z",
                    "end_time": "2026-03-09T09:00:00Z",
                    "attendees": ["bad-email"],
                }
            ),
            "invalid_email",
        ),
        (
            lambda monkeypatch: None,
            lambda: gmail._gmail_unread({"label_ids": [f"label{i}" for i in range(25)]}),
            "too_many_labels",
        ),
        (
            lambda monkeypatch: monkeypatch.setattr(auth, "_build_service", lambda *args, **kwargs: _DriveService()),
            lambda: drive._drive_recent_files({"query": "x" * 1001}),
            "query_too_long",
        ),
        (
            lambda monkeypatch: monkeypatch.setenv("MW_GOOGLE_DRIVE_WRITE_ENABLED", "true"),
            lambda: drive._drive_create_text_file({"file_name": "big.txt", "content": "x" * (10 * 1024 * 1024 + 1)}),
            "content_too_large",
        ),
        (
            lambda monkeypatch: monkeypatch.setenv("MW_GOOGLE_DOCS_WRITE_ENABLED", "true"),
            lambda: docs._docs_create({"title": "Big Doc", "content": "x" * (10 * 1024 * 1024 + 1)}),
            "content_too_large",
        ),
    ],
)
def test_google_workspace_validation_guards(monkeypatch, setup, call, error_code):
    setup(monkeypatch)
    result = call()
    assert result["status"] == "error"
    assert result["error"]["code"] == error_code


def test_get_tools_returns_all():
    from services.mcp_server.plugins.workspace.google_workspace_tools import get_tools
    tools = get_tools()
    names = [t.name for t in tools]
    assert "google_calendar_events" in names
    assert "gmail_unread" in names
    assert "google_drive_recent_files" in names
    assert "google_sheets_read_range" in names
    assert "google_docs_get" in names
    assert "google_photos_list_albums" in names
    assert "google_maps_compute_route" in names
    assert "notebooklm_query_notebook" in names
    assert len(tools) == 34
