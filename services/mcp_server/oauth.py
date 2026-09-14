from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response

from .plugins.workspace.google_tools import _auth as google_auth
from .plugins.workspace.google_tools import _capabilities

READ_SCOPE: Final = "workspace:read"
WRITE_SCOPE: Final = "workspace:write"
LOCAL_SUBJECT: Final = "local-user"
DEFAULT_STATE_FILE: Final = "/secrets/mcp-oauth-state.json"
PENDING_TTL_SECONDS: Final = 600
AUTH_CODE_TTL_SECONDS: Final = 300
ACCESS_TOKEN_TTL_SECONDS: Final = 900
REFRESH_TOKEN_TTL_SECONDS: Final = 30 * 24 * 60 * 60
LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "localhost", "::1"})


def _dedupe_scopes(scopes: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(scopes))


READONLY_GOOGLE_SCOPES: Final = _dedupe_scopes(
    [
        *_capabilities.CALENDAR_SCOPES,
        *_capabilities.GMAIL_SCOPES,
        *_capabilities.DRIVE_SCOPES,
        *_capabilities.SHEETS_SCOPES,
        *_capabilities.DOCS_SCOPES,
        *_capabilities.PHOTOS_READ_SCOPES,
    ]
)
POWER_GOOGLE_SCOPES: Final = _dedupe_scopes(
    [
        *READONLY_GOOGLE_SCOPES,
        *_capabilities.CALENDAR_WRITE_SCOPES,
        *_capabilities.GMAIL_SEND_SCOPES,
        *_capabilities.DRIVE_WRITE_SCOPES,
        *_capabilities.SHEETS_WRITE_SCOPES,
        *_capabilities.DOCS_WRITE_SCOPES,
        *_capabilities.PHOTOS_WRITE_SCOPES,
    ]
)


def active_mcp_scopes(profile: str) -> list[str]:
    return [READ_SCOPE, WRITE_SCOPE] if profile == "power" else [READ_SCOPE]


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_google_flow(
    credentials_path: Path,
    scopes: tuple[str, ...],
    state: str,
    redirect_uri: str,
    *,
    code_verifier: str | None = None,
):
    from google_auth_oauthlib.flow import Flow

    callback = urlparse(redirect_uri)
    if callback.scheme == "http":
        if callback.hostname not in LOOPBACK_HOSTS:
            raise ValueError("Google OAuth HTTP callbacks must use a loopback host")
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    # Google can return previously granted scopes in addition to this request.
    # The callback validates that every requested scope is still present.
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

    flow = Flow.from_client_secrets_file(
        str(credentials_path),
        scopes=list(scopes),
        state=state,
        code_verifier=code_verifier,
        autogenerate_code_verifier=code_verifier is None,
    )
    flow.redirect_uri = redirect_uri
    return flow


@dataclass(frozen=True)
class PendingAuthorization:
    expires_at: float
    client_id: str
    client_state: str | None
    scopes: list[str]
    code_challenge: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    resource: str
    google_scopes: tuple[str, ...]
    google_code_verifier: str


class LocalGoogleOAuthProvider:
    """Single-user OAuth bridge between Codex MCP auth and Google consent."""

    def __init__(
        self,
        *,
        issuer: str,
        resource: str,
        state_path: Path | None = None,
        google_credentials_path: Path | None = None,
        google_token_path: Path | None = None,
        profile: str = "readonly",
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.resource = resource
        self.profile = profile
        self.state_path = state_path or Path(os.getenv("MW_MCP_OAUTH_STATE_FILE", DEFAULT_STATE_FILE))
        self.google_credentials_path = google_credentials_path or google_auth.credentials_file()
        self.google_token_path = google_token_path or google_auth.token_file()
        self.google_callback_url = f"{self.issuer}/oauth/google/callback"
        self._lock = threading.RLock()
        self._pending: dict[str, PendingAuthorization] = {}
        self._authorization_codes: dict[str, AuthorizationCode] = {}
        self._state = self._load_state()

    @property
    def configured(self) -> bool:
        return self.google_credentials_path.is_file()

    @property
    def google_connected(self) -> bool:
        try:
            payload = json.loads(self.google_token_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return bool(payload.get("refresh_token") or payload.get("token"))

    def _empty_state(self) -> dict[str, dict[str, Any]]:
        return {"clients": {}, "access_tokens": {}, "refresh_tokens": {}}

    def _load_state(self) -> dict[str, dict[str, Any]]:
        if not self.state_path.exists():
            return self._empty_state()
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise TypeError("OAuth state root must be an object")
            state = {
                key: dict(raw.get(key) or {})
                for key in ("clients", "access_tokens", "refresh_tokens")
            }
            if any(not isinstance(item, dict) for section in state.values() for item in section.values()):
                raise ValueError("OAuth state records must be objects")
            for client in state["clients"].values():
                OAuthClientInformationFull.model_validate(client)
            token_fields = {"client_id", "scopes", "subject", "resource", "family", "expires_at"}
            if any(
                not token_fields.issubset(record) or not isinstance(record["scopes"], list)
                for key in ("access_tokens", "refresh_tokens")
                for record in state[key].values()
            ):
                raise ValueError("OAuth token records are invalid")
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RuntimeError(f"invalid MCP OAuth state file: {self.state_path}") from exc
        os.chmod(self.state_path, 0o600)
        return state

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.state_path.parent,
                prefix=f".{self.state_path.name}.",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                os.chmod(temporary.name, 0o600)
                json.dump(self._state, temporary, sort_keys=True, separators=(",", ":"))
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, self.state_path)
            temporary_name = None
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)

    def _prune(self) -> bool:
        now = int(time.time())
        changed = False
        for key in ("access_tokens", "refresh_tokens"):
            records = self._state[key]
            expired = [token_hash for token_hash, item in records.items() if item.get("expires_at", 0) < now]
            for token_hash in expired:
                del records[token_hash]
                changed = True
        return changed

    def _remove_family(self, family: str) -> None:
        for key in ("access_tokens", "refresh_tokens"):
            records = self._state[key]
            for token_hash in [value for value, item in records.items() if item.get("family") == family]:
                del records[token_hash]

    def _prune_ephemeral(self) -> None:
        now = time.time()
        for state in [key for key, item in self._pending.items() if item.expires_at < now]:
            del self._pending[state]
        for code in [key for key, item in self._authorization_codes.items() if item.expires_at < now]:
            del self._authorization_codes[code]

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with self._lock:
            payload = self._state["clients"].get(client_id)
            return OAuthClientInformationFull.model_validate(payload) if payload else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        redirect_uris = client_info.redirect_uris or []
        if not redirect_uris or any(
            urlparse(str(uri)).scheme != "http" or urlparse(str(uri)).hostname not in LOOPBACK_HOSTS
            for uri in redirect_uris
        ):
            raise RegistrationError(
                error="invalid_redirect_uri",
                error_description="only loopback HTTP redirect URIs are allowed",
            )
        with self._lock:
            self._state["clients"][client_info.client_id] = client_info.model_dump(mode="json")
            self._save_state()

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if params.resource != self.resource:
            raise AuthorizeError(error="invalid_target", error_description="invalid MCP resource")
        scopes = list(params.scopes or [])
        if not scopes or any(scope not in active_mcp_scopes(self.profile) for scope in scopes):
            raise AuthorizeError(error="invalid_scope", error_description="scope is not enabled by the active profile")
        if not self.configured:
            raise AuthorizeError(error="server_error", error_description="Google OAuth client is not configured")

        google_scopes = POWER_GOOGLE_SCOPES if WRITE_SCOPE in scopes else READONLY_GOOGLE_SCOPES
        bridge_state = secrets.token_urlsafe(32)
        flow = _new_google_flow(
            self.google_credentials_path,
            google_scopes,
            bridge_state,
            self.google_callback_url,
        )
        authorization_url, returned_state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="select_account consent",
        )
        if returned_state != bridge_state:
            raise AuthorizeError(error="server_error", error_description="Google state setup failed")
        if not flow.code_verifier:
            raise AuthorizeError(error="server_error", error_description="Google PKCE setup failed")
        pending = PendingAuthorization(
            expires_at=time.time() + PENDING_TTL_SECONDS,
            client_id=client.client_id,
            client_state=params.state,
            scopes=scopes,
            code_challenge=params.code_challenge,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=self.resource,
            google_scopes=google_scopes,
            google_code_verifier=flow.code_verifier,
        )
        with self._lock:
            self._prune_ephemeral()
            self._pending[returned_state] = pending
        return authorization_url

    async def handle_google_callback(self, request: Request) -> Response:
        bridge_state = request.query_params.get("state", "")
        with self._lock:
            pending = self._pending.pop(bridge_state, None)
        if pending is None or pending.expires_at < time.time():
            return PlainTextResponse(
                "Google authorization state is invalid or expired.",
                status_code=400,
                headers={"Cache-Control": "no-store"},
            )

        if request.query_params.get("error"):
            return RedirectResponse(
                construct_redirect_uri(
                    pending.redirect_uri,
                    error="access_denied",
                    error_description="Google authorization was denied",
                    state=pending.client_state,
                ),
                status_code=302,
                headers={"Cache-Control": "no-store"},
            )

        try:
            flow = _new_google_flow(
                self.google_credentials_path,
                pending.google_scopes,
                bridge_state,
                self.google_callback_url,
                code_verifier=pending.google_code_verifier,
            )
            flow.fetch_token(authorization_response=str(request.url))
            credentials = flow.credentials
            granted_scopes = set(credentials.scopes or [])
            if not credentials.valid or not set(pending.google_scopes).issubset(granted_scopes):
                raise ValueError("Google did not grant all requested scopes")
            google_auth.write_token_json(self.google_token_path, credentials.to_json())
        except Exception:  # noqa: BLE001 - keep third-party OAuth failures out of browser responses
            return PlainTextResponse(
                "Google authorization failed. Run make login and try again.",
                status_code=502,
                headers={"Cache-Control": "no-store"},
            )

        code_value = secrets.token_urlsafe(32)
        authorization_code = AuthorizationCode(
            code=code_value,
            scopes=pending.scopes,
            expires_at=time.time() + AUTH_CODE_TTL_SECONDS,
            client_id=pending.client_id,
            code_challenge=pending.code_challenge,
            redirect_uri=pending.redirect_uri,
            redirect_uri_provided_explicitly=pending.redirect_uri_provided_explicitly,
            resource=pending.resource,
            subject=LOCAL_SUBJECT,
        )
        with self._lock:
            self._authorization_codes[code_value] = authorization_code
        return RedirectResponse(
            construct_redirect_uri(
                pending.redirect_uri,
                code=code_value,
                state=pending.client_state,
            ),
            status_code=302,
            headers={"Cache-Control": "no-store"},
        )

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        with self._lock:
            self._prune_ephemeral()
            code = self._authorization_codes.get(authorization_code)
            if code is None or code.client_id != client.client_id:
                return None
            return code

    def _issue_tokens(self, client_id: str, scopes: list[str], resource: str) -> OAuthToken:
        now = int(time.time())
        family = secrets.token_urlsafe(24)
        access_value = secrets.token_urlsafe(32)
        refresh_value = secrets.token_urlsafe(48)
        common = {
            "client_id": client_id,
            "scopes": scopes,
            "subject": LOCAL_SUBJECT,
            "resource": resource,
            "family": family,
        }
        self._state["access_tokens"][_token_hash(access_value)] = {
            **common,
            "expires_at": now + ACCESS_TOKEN_TTL_SECONDS,
        }
        self._state["refresh_tokens"][_token_hash(refresh_value)] = {
            **common,
            "expires_at": now + REFRESH_TOKEN_TTL_SECONDS,
        }
        self._save_state()
        return OAuthToken(
            access_token=access_value,
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(scopes),
            refresh_token=refresh_value,
        )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        with self._lock:
            stored = self._authorization_codes.pop(authorization_code.code, None)
            if stored is None or stored.client_id != client.client_id or stored.resource != self.resource:
                raise TokenError(error="invalid_grant", error_description="authorization code is invalid")
            return self._issue_tokens(client.client_id, stored.scopes, self.resource)

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        with self._lock:
            changed = self._prune()
            record = self._state["refresh_tokens"].get(_token_hash(refresh_token))
            if changed:
                self._save_state()
            if record is None or record["client_id"] != client.client_id or record["resource"] != self.resource:
                return None
            return RefreshToken(
                token=refresh_token,
                client_id=record["client_id"],
                scopes=record["scopes"],
                expires_at=record["expires_at"],
                subject=record["subject"],
            )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        if any(scope not in active_mcp_scopes(self.profile) for scope in scopes):
            raise TokenError(error="invalid_scope", error_description="scope is not enabled by the active profile")
        with self._lock:
            record = self._state["refresh_tokens"].get(_token_hash(refresh_token.token))
            if record is None or record["client_id"] != client.client_id or record["resource"] != self.resource:
                raise TokenError(error="invalid_grant", error_description="refresh token is invalid")
            self._remove_family(record["family"])
            return self._issue_tokens(client.client_id, scopes, self.resource)

    async def load_access_token(self, token: str) -> AccessToken | None:
        with self._lock:
            changed = self._prune()
            record = self._state["access_tokens"].get(_token_hash(token))
            if changed:
                self._save_state()
            if record is None or record["resource"] != self.resource:
                return None
            return AccessToken(
                token=token,
                client_id=record["client_id"],
                scopes=record["scopes"],
                expires_at=record["expires_at"],
                resource=record["resource"],
                subject=record["subject"],
                claims={"profile": self.profile},
            )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        with self._lock:
            token_key = _token_hash(token.token)
            record = self._state["access_tokens"].get(token_key) or self._state["refresh_tokens"].get(token_key)
            if record is None:
                return
            self._remove_family(record["family"])
            self._save_state()
