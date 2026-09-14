from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from google.auth.exceptions import RefreshError
from mcp.server.auth.provider import (
    AuthorizationParams,
    AuthorizeError,
    RegistrationError,
)
from mcp.shared.auth import OAuthClientInformationFull
from oauthlib.oauth2 import is_secure_transport
from starlette.applications import Starlette
from starlette.routing import Route

from services.mcp_server import oauth
from services.mcp_server.app import create_app
from services.mcp_server.plugins.workspace.google_tools import _auth as google_auth
from services.mcp_server.plugins.workspace.google_tools import _calendar


def run(coro):
    return asyncio.run(coro)


def client(redirect_uri: str = "http://127.0.0.1/callback/test") -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="codex-client",
        client_secret="client-secret",
        redirect_uris=[redirect_uri],
        token_endpoint_auth_method="client_secret_post",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope="workspace:read workspace:write",
    )


def provider(tmp_path: Path) -> oauth.LocalGoogleOAuthProvider:
    tmp_path.mkdir(parents=True, exist_ok=True)
    credentials = tmp_path / "google-credentials.json"
    credentials.write_text('{"installed": {}}', encoding="utf-8")
    return oauth.LocalGoogleOAuthProvider(
        issuer="http://127.0.0.1:8066",
        resource="http://127.0.0.1:8066/mcp",
        state_path=tmp_path / "mcp-oauth-state.json",
        google_credentials_path=credentials,
        google_token_path=tmp_path / "google-token.json",
        profile="readonly",
    )


def test_registration_is_persistent_and_loopback_only(tmp_path):
    first = provider(tmp_path)
    run(first.register_client(client()))

    restarted = provider(tmp_path)
    loaded = run(restarted.get_client("codex-client"))
    assert loaded is not None
    assert loaded.client_secret == "client-secret"
    assert oct((tmp_path / "mcp-oauth-state.json").stat().st_mode & 0o777) == "0o600"

    with pytest.raises(RegistrationError):
        run(first.register_client(client("https://example.com/callback")))


def test_google_flow_allows_http_only_for_loopback(monkeypatch, tmp_path):
    monkeypatch.delenv("OAUTHLIB_INSECURE_TRANSPORT", raising=False)
    monkeypatch.delenv("OAUTHLIB_RELAX_TOKEN_SCOPE", raising=False)
    credentials = tmp_path / "google-credentials.json"
    credentials.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "test.apps.googleusercontent.com",
                    "project_id": "test",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "client_secret": "test",
                    "redirect_uris": ["http://localhost"],
                }
            }
        ),
        encoding="utf-8",
    )
    callback = "http://127.0.0.1:8066/oauth/google/callback"

    oauth._new_google_flow(
        credentials,
        oauth.READONLY_GOOGLE_SCOPES,
        "state",
        callback,
        code_verifier="v" * 64,
    )

    assert is_secure_transport(callback)
    assert os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] == "1"


def test_google_bridge_issues_resource_bound_rotating_tokens(monkeypatch, tmp_path):
    auth_provider = provider(tmp_path)
    oauth_client = client()
    run(auth_provider.register_client(oauth_client))

    class FakeCredentials:
        valid = True
        refresh_token = "google-refresh"

        def __init__(self):
            self.scopes = list(oauth.READONLY_GOOGLE_SCOPES)

        def to_json(self):
            return '{"refresh_token":"google-refresh","scopes":' + str(self.scopes).replace("'", '"') + "}"

    class FakeFlow:
        credentials = FakeCredentials()
        redirect_uri = None

        def __init__(self, state, code_verifier=None):
            self.state = state
            self.code_verifier = code_verifier or "generated-google-verifier"

        def authorization_url(self, **kwargs):
            assert kwargs["access_type"] == "offline"
            assert kwargs["prompt"] == "select_account consent"
            return f"https://accounts.google.test/auth?state={self.state}", self.state

        def fetch_token(self, authorization_response):
            assert "code=google-code" in authorization_response

    seen_google_verifiers = []

    def fake_flow(*args, code_verifier=None, **kwargs):
        seen_google_verifiers.append(code_verifier)
        return FakeFlow(args[2], code_verifier)

    monkeypatch.setattr(oauth, "_new_google_flow", fake_flow)
    params = AuthorizationParams(
        state="codex-state",
        scopes=[oauth.READ_SCOPE],
        code_challenge="challenge",
        redirect_uri="http://127.0.0.1/callback/test",
        redirect_uri_provided_explicitly=True,
        resource="http://127.0.0.1:8066/mcp",
    )

    location = run(auth_provider.authorize(oauth_client, params))
    assert location.startswith("https://accounts.google.test/")
    bridge_state = parse_qs(urlparse(location).query)["state"][0]

    app = Starlette(routes=[Route("/oauth/google/callback", auth_provider.handle_google_callback)])
    with TestClient(app) as test_client:
        response = test_client.get(
            f"/oauth/google/callback?state={bridge_state}&code=google-code",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert seen_google_verifiers == [None, "generated-google-verifier"]
    assert oct((tmp_path / "google-token.json").stat().st_mode & 0o777) == "0o600"
    redirect = urlparse(response.headers["location"])
    query = parse_qs(redirect.query)
    assert query["state"] == ["codex-state"]
    code_value = query["code"][0]

    auth_code = run(auth_provider.load_authorization_code(oauth_client, code_value))
    assert auth_code is not None
    first_tokens = run(auth_provider.exchange_authorization_code(oauth_client, auth_code))
    access = run(auth_provider.load_access_token(first_tokens.access_token))
    assert access is not None
    assert access.resource == "http://127.0.0.1:8066/mcp"
    assert access.scopes == [oauth.READ_SCOPE]
    monkeypatch.setattr(oauth.time, "time", lambda: access.expires_at + 1)
    assert run(auth_provider.load_access_token(first_tokens.access_token)) is None

    restarted = provider(tmp_path)
    refresh = run(restarted.load_refresh_token(oauth_client, first_tokens.refresh_token))
    assert refresh is not None
    second_tokens = run(restarted.exchange_refresh_token(oauth_client, refresh, [oauth.READ_SCOPE]))
    assert run(restarted.load_refresh_token(oauth_client, first_tokens.refresh_token)) is None
    second_access = run(restarted.load_access_token(second_tokens.access_token))
    assert second_access is not None

    wrong_resource = oauth.LocalGoogleOAuthProvider(
        issuer="http://127.0.0.1:8066",
        resource="http://127.0.0.1:8066/other",
        state_path=tmp_path / "mcp-oauth-state.json",
        google_credentials_path=tmp_path / "google-credentials.json",
        google_token_path=tmp_path / "google-token.json",
    )
    assert run(wrong_resource.load_access_token(second_tokens.access_token)) is None

    token_payload = (tmp_path / "mcp-oauth-state.json").read_text(encoding="utf-8")
    assert first_tokens.access_token not in token_payload
    assert first_tokens.refresh_token not in token_payload
    assert hashlib.sha256(second_tokens.access_token.encode()).hexdigest() in token_payload

    run(restarted.revoke_token(second_access))
    assert run(restarted.load_access_token(second_tokens.access_token)) is None
    assert run(restarted.load_refresh_token(oauth_client, second_tokens.refresh_token)) is None


def test_oauth_transport_advertises_discovery_and_scopes(monkeypatch, tmp_path):
    credentials = tmp_path / "google-credentials.json"
    credentials.write_text('{"installed": {}}', encoding="utf-8")
    monkeypatch.setenv("MW_MCP_AUTH_MODE", "oauth")
    monkeypatch.setenv("MW_PROFILE", "readonly")
    monkeypatch.setenv("MW_MCP_CLIENT_URL", "http://127.0.0.1:8066/mcp")
    monkeypatch.setenv("MW_MCP_OAUTH_STATE_FILE", str(tmp_path / "mcp-oauth-state.json"))
    monkeypatch.setenv("MW_GOOGLE_CREDENTIALS_FILE", str(credentials))
    monkeypatch.setenv("MW_GOOGLE_TOKEN_FILE", str(tmp_path / "google-token.json"))

    with TestClient(create_app()) as test_client:
        unauthorized = test_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert unauthorized.status_code == 401
        assert "resource_metadata=" in unauthorized.headers["www-authenticate"]

        metadata = test_client.get("/.well-known/oauth-authorization-server")
        assert metadata.status_code == 200
        payload = metadata.json()
        assert payload["issuer"] == "http://127.0.0.1:8066"
        assert payload["registration_endpoint"].endswith("/register")
        assert payload["code_challenge_methods_supported"] == ["S256"]
        assert payload["scopes_supported"] == [oauth.READ_SCOPE]

        health = test_client.get("/healthz").json()
        assert health["auth"] == {
            "configured": True,
            "google_connected": False,
            "type": "oauth",
        }


def test_power_profile_requires_both_mcp_scopes(monkeypatch, tmp_path):
    monkeypatch.setenv("MW_MCP_AUTH_MODE", "oauth")
    monkeypatch.setenv("MW_PROFILE", "power")
    monkeypatch.setenv("MW_MCP_OAUTH_STATE_FILE", str(tmp_path / "mcp-oauth-state.json"))
    monkeypatch.setenv("MW_GOOGLE_CREDENTIALS_FILE", str(tmp_path / "missing.json"))
    monkeypatch.setenv("MW_GOOGLE_TOKEN_FILE", str(tmp_path / "missing-token.json"))

    with TestClient(create_app()) as test_client:
        metadata = test_client.get("/.well-known/oauth-authorization-server").json()
    assert metadata["scopes_supported"] == [oauth.READ_SCOPE, oauth.WRITE_SCOPE]


def test_power_consent_requests_complete_workspace_scope_set(monkeypatch, tmp_path):
    credentials = tmp_path / "google-credentials.json"
    credentials.write_text('{"installed": {}}', encoding="utf-8")
    auth_provider = oauth.LocalGoogleOAuthProvider(
        issuer="http://127.0.0.1:8066",
        resource="http://127.0.0.1:8066/mcp",
        state_path=tmp_path / "mcp-oauth-state.json",
        google_credentials_path=credentials,
        google_token_path=tmp_path / "google-token.json",
        profile="power",
    )
    oauth_client = client()
    run(auth_provider.register_client(oauth_client))
    captured = {}

    class FakeFlow:
        code_verifier = "generated-google-verifier"

        def __init__(self, state):
            self.state = state

        def authorization_url(self, **kwargs):
            return f"https://accounts.google.test/auth?state={self.state}", self.state

    def fake_flow(credentials_path, scopes, state, redirect_uri):
        captured["scopes"] = scopes
        return FakeFlow(state)

    monkeypatch.setattr(oauth, "_new_google_flow", fake_flow)
    location = run(
        auth_provider.authorize(
            oauth_client,
            AuthorizationParams(
                state="codex-state",
                scopes=[oauth.READ_SCOPE, oauth.WRITE_SCOPE],
                code_challenge="challenge",
                redirect_uri="http://127.0.0.1/callback/test",
                redirect_uri_provided_explicitly=True,
                resource="http://127.0.0.1:8066/mcp",
            ),
        )
    )
    assert location.startswith("https://accounts.google.test/")
    assert captured["scopes"] == oauth.POWER_GOOGLE_SCOPES

    readonly = provider(tmp_path / "readonly")
    run(readonly.register_client(oauth_client))
    with pytest.raises(AuthorizeError):
        run(
            readonly.authorize(
                oauth_client,
                AuthorizationParams(
                    state="codex-state",
                    scopes=[oauth.READ_SCOPE, oauth.WRITE_SCOPE],
                    code_challenge="challenge",
                    redirect_uri="http://127.0.0.1/callback/test",
                    redirect_uri_provided_explicitly=True,
                    resource="http://127.0.0.1:8066/mcp",
                ),
            )
        )


def test_full_sdk_oauth_flow_uses_dcr_pkce_and_resource(monkeypatch, tmp_path):
    credentials_path = tmp_path / "google-credentials.json"
    credentials_path.write_text('{"installed": {}}', encoding="utf-8")
    monkeypatch.setenv("MW_MCP_AUTH_MODE", "oauth")
    monkeypatch.setenv("MW_PROFILE", "readonly")
    monkeypatch.setenv("MW_MCP_CLIENT_URL", "http://127.0.0.1:8066/mcp")
    monkeypatch.setenv("MW_MCP_OAUTH_STATE_FILE", str(tmp_path / "mcp-oauth-state.json"))
    monkeypatch.setenv("MW_GOOGLE_CREDENTIALS_FILE", str(credentials_path))
    monkeypatch.setenv("MW_GOOGLE_TOKEN_FILE", str(tmp_path / "google-token.json"))

    class FakeCredentials:
        valid = True
        refresh_token = "google-refresh"

        def __init__(self):
            self.scopes = list(oauth.READONLY_GOOGLE_SCOPES)

        def to_json(self):
            return json.dumps({"refresh_token": self.refresh_token, "scopes": self.scopes})

    class FakeFlow:
        credentials = FakeCredentials()

        def __init__(self, state, code_verifier=None):
            self.state = state
            self.code_verifier = code_verifier or "generated-google-verifier"

        def authorization_url(self, **kwargs):
            return f"https://accounts.google.test/auth?state={self.state}", self.state

        def fetch_token(self, authorization_response):
            assert "code=google-code" in authorization_response

    monkeypatch.setattr(
        oauth,
        "_new_google_flow",
        lambda credentials, scopes, state, redirect_uri, **kwargs: FakeFlow(
            state, kwargs.get("code_verifier")
        ),
    )

    verifier = "v" * 48
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    callback = "http://127.0.0.1/callback/test"

    with TestClient(create_app()) as test_client:
        registration = test_client.post(
            "/register",
            json={
                "client_name": "Codex test",
                "redirect_uris": [callback],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": oauth.READ_SCOPE,
            },
        )
        assert registration.status_code == 201, registration.text
        registered = registration.json()
        assert "client_secret" not in registered or registered["client_secret"] is None

        rejected = test_client.post(
            "/register",
            json={
                "redirect_uris": ["https://example.com/callback"],
                "token_endpoint_auth_method": "client_secret_post",
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "scope": oauth.READ_SCOPE,
            },
        )
        assert rejected.status_code == 400
        assert rejected.json()["error"] == "invalid_redirect_uri"

        authorize = test_client.get(
            "/authorize",
            params={
                "client_id": registered["client_id"],
                "response_type": "code",
                "redirect_uri": callback,
                "scope": oauth.READ_SCOPE,
                "state": "codex-state",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": "http://127.0.0.1:8066/mcp",
            },
            follow_redirects=False,
        )
        assert authorize.status_code == 302, authorize.text
        bridge_state = parse_qs(urlparse(authorize.headers["location"]).query)["state"][0]

        google_callback = test_client.get(
            "/oauth/google/callback",
            params={"state": bridge_state, "code": "google-code"},
            follow_redirects=False,
        )
        assert google_callback.status_code == 302, google_callback.text
        code_value = parse_qs(urlparse(google_callback.headers["location"]).query)["code"][0]

        wrong_verifier = test_client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": registered["client_id"],
                "code": code_value,
                "code_verifier": "wrong-verifier",
                "redirect_uri": callback,
            },
        )
        assert wrong_verifier.status_code == 400
        assert wrong_verifier.json()["error"] == "invalid_grant"

        token_response = test_client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": registered["client_id"],
                "code": code_value,
                "code_verifier": verifier,
                "redirect_uri": callback,
            },
        )
        assert token_response.status_code == 200, token_response.text
        tokens = token_response.json()

        replayed_code = test_client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": registered["client_id"],
                "code": code_value,
                "code_verifier": verifier,
                "redirect_uri": callback,
            },
        )
        assert replayed_code.status_code == 400
        assert replayed_code.json()["error"] == "invalid_grant"

        listed = test_client.post(
            "/mcp",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert listed.status_code == 200, listed.text
        assert len(listed.json()["result"]["tools"]) == 34


def test_google_consent_denial_preserves_existing_token(monkeypatch, tmp_path):
    auth_provider = provider(tmp_path)
    oauth_client = client()
    run(auth_provider.register_client(oauth_client))
    existing = tmp_path / "google-token.json"
    existing.write_text("existing-token", encoding="utf-8")

    class FakeFlow:
        code_verifier = "generated-google-verifier"

        def __init__(self, state):
            self.state = state

        def authorization_url(self, **kwargs):
            return f"https://accounts.google.test/auth?state={self.state}", self.state

    monkeypatch.setattr(oauth, "_new_google_flow", lambda *args, **kwargs: FakeFlow(args[2]))
    location = run(
        auth_provider.authorize(
            oauth_client,
            AuthorizationParams(
                state="codex-state",
                scopes=[oauth.READ_SCOPE],
                code_challenge="challenge",
                redirect_uri="http://127.0.0.1/callback/test",
                redirect_uri_provided_explicitly=True,
                resource="http://127.0.0.1:8066/mcp",
            ),
        )
    )
    bridge_state = parse_qs(urlparse(location).query)["state"][0]

    app = Starlette(routes=[Route("/oauth/google/callback", auth_provider.handle_google_callback)])
    with TestClient(app) as test_client:
        denied = test_client.get(
            "/oauth/google/callback",
            params={"state": bridge_state, "error": "access_denied"},
            follow_redirects=False,
        )
        replay = test_client.get(
            "/oauth/google/callback",
            params={"state": bridge_state, "error": "access_denied"},
            follow_redirects=False,
        )

    assert denied.status_code == 302
    assert parse_qs(urlparse(denied.headers["location"]).query)["error"] == ["access_denied"]
    assert replay.status_code == 400
    assert existing.read_text(encoding="utf-8") == "existing-token"


def test_invalid_persisted_oauth_state_fails_closed(tmp_path):
    state_path = tmp_path / "mcp-oauth-state.json"
    state_path.write_text("not-json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="invalid MCP OAuth state file"):
        oauth.LocalGoogleOAuthProvider(
            issuer="http://127.0.0.1:8066",
            resource="http://127.0.0.1:8066/mcp",
            state_path=state_path,
            google_credentials_path=tmp_path / "google-credentials.json",
            google_token_path=tmp_path / "google-token.json",
        )

    state_path.write_text("[]", encoding="utf-8")
    with pytest.raises(RuntimeError, match="invalid MCP OAuth state file"):
        oauth.LocalGoogleOAuthProvider(
            issuer="http://127.0.0.1:8066",
            resource="http://127.0.0.1:8066/mcp",
            state_path=state_path,
            google_credentials_path=tmp_path / "google-credentials.json",
            google_token_path=tmp_path / "google-token.json",
        )


def test_invalid_auth_mode_fails_closed(monkeypatch):
    monkeypatch.setenv("MW_MCP_AUTH_MODE", "both")
    with pytest.raises(ValueError, match="MW_MCP_AUTH_MODE"):
        create_app()


def test_google_tool_returns_reauth_required(monkeypatch):
    monkeypatch.setenv("MW_GOOGLE_CALENDAR_READ_ENABLED", "true")
    monkeypatch.setattr(
        _calendar._auth,
        "_build_service",
        lambda *args: (_ for _ in ()).throw(google_auth.GoogleReauthRequired("secret detail")),
    )

    result = _calendar._calendar_events(
        {
            "time_min": "2026-09-01T00:00:00Z",
            "time_max": "2026-09-02T00:00:00Z",
        }
    )

    assert result["status"] == "error"
    assert result["error"] == {
        "code": "reauth_required",
        "message": "Google authorization is required. Use Codex Authenticate or run make login.",
        "details": None,
    }

    monkeypatch.setattr(
        _calendar._auth,
        "_build_service",
        lambda *args: (_ for _ in ()).throw(RefreshError("provider detail")),
    )
    refresh_failure = _calendar._calendar_events(
        {
            "time_min": "2026-09-01T00:00:00Z",
            "time_max": "2026-09-02T00:00:00Z",
        }
    )
    assert refresh_failure["error"]["code"] == "reauth_required"
    assert "provider detail" not in refresh_failure["error"]["message"]


def test_missing_google_token_raises_reauth_required(monkeypatch, tmp_path):
    monkeypatch.setenv("MW_GOOGLE_TOKEN_FILE", str(tmp_path / "missing-token.json"))
    with pytest.raises(google_auth.GoogleReauthRequired):
        google_auth.get_credentials(list(oauth.READONLY_GOOGLE_SCOPES))


def test_persisted_google_scopes_are_checked_before_use(monkeypatch, tmp_path):
    token_path = tmp_path / "google-token.json"
    token_path.write_text(
        json.dumps(
            {
                "token": "access",
                "refresh_token": "refresh",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "client",
                "client_secret": "secret",
                "scopes": ["https://www.googleapis.com/auth/calendar.readonly"],
                "expiry": "2999-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MW_GOOGLE_TOKEN_FILE", str(token_path))

    with pytest.raises(google_auth.GoogleReauthRequired, match="missing required scopes"):
        google_auth.get_credentials(["https://www.googleapis.com/auth/gmail.readonly"])
