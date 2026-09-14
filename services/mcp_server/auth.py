from __future__ import annotations

import os
import secrets

from mcp.server.auth.provider import AccessToken, TokenVerifier

API_KEY_ENV = "MW_API_KEY"
AUTH_MODE_ENV = "MW_MCP_AUTH_MODE"
AUTH_MODES = frozenset({"oauth", "api_key"})


def auth_mode() -> str:
    mode = os.getenv(AUTH_MODE_ENV, "oauth").strip().lower() or "oauth"
    if mode not in AUTH_MODES:
        raise ValueError(f"{AUTH_MODE_ENV} must be one of: api_key, oauth")
    return mode


def api_key_configured() -> bool:
    return bool(os.getenv(API_KEY_ENV, "").strip())


class WorkspaceTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        expected = os.getenv(API_KEY_ENV, "").strip()
        if not expected or not secrets.compare_digest(token, expected):
            return None
        return AccessToken(
            token=token,
            client_id="mythosaur-workspace-user",
            scopes=[],
            subject="mythosaur-workspace-user",
            claims={"profile": os.getenv("MW_PROFILE", "readonly")},
        )
