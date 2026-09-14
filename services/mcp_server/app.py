from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI
from mcp.server.auth.provider import ProviderTokenVerifier
from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
    ToolAnnotations,
)
from starlette.routing import Route

from .auth import WorkspaceTokenVerifier, api_key_configured, auth_mode
from .oauth import LocalGoogleOAuthProvider, active_mcp_scopes
from .plugins.common import ToolDef, ToolResultEnvelope, err, now_ms
from .plugins.workspace.google_plugin import PLUGIN_SPEC
from .plugins.workspace.google_workspace_tools import get_tools

SERVICE_NAME = "mythosaur-workspace"
API_VERSION = "0.1.0"
DEFAULT_MCP_URL = "http://127.0.0.1:8066/mcp"
logging.basicConfig(level=os.getenv("MW_LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)


def load_tools() -> dict[str, ToolDef]:
    tools: dict[str, ToolDef] = {}
    for raw_tool in get_tools():
        tool = PLUGIN_SPEC.bind(raw_tool)
        if tool.name in tools:
            raise ValueError(f"duplicate tool: {tool.name}")
        tools[tool.name] = tool
    if len(tools) != 34:
        raise ValueError(f"expected 34 Workspace tools, found {len(tools)}")
    return tools


def _sdk_tool(tool: ToolDef) -> Tool:
    mutates = bool(tool.mutates_state)
    return Tool(
        name=tool.name,
        description=tool.description,
        inputSchema=tool.input_schema,
        outputSchema=ToolResultEnvelope.model_json_schema(),
        annotations=ToolAnnotations(
            read_only_hint=not mutates,
            destructive_hint=tool.destructive,
            idempotent_hint=not mutates,
            open_world_hint=True,
        ),
        _meta={
            "io.mythosaur/tool": {
                "pluginId": tool.plugin_id,
                "category": tool.category,
                "requiredCapability": tool.required_capability,
                "mutatesState": mutates,
                "auditAction": tool.audit_action,
            }
        },
    )


async def _invoke(tool: ToolDef, arguments: dict[str, Any]) -> dict[str, Any]:
    started = now_ms()
    try:
        result = await tool.invoke(arguments)
        return ToolResultEnvelope.model_validate(result).model_dump(mode="json")
    except ValueError as exc:
        return err(tool.name, "validation_error", str(exc), tool.plugin_id, started)
    except Exception as exc:
        logger.exception("tool execution failed: %s", tool.name)
        return err(tool.name, "internal_error", str(exc), tool.plugin_id, started)


def create_mcp_app(tools: dict[str, ToolDef]):
    async def list_tools(
        _ctx: ServerRequestContext[Any, Any],
        _params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        return ListToolsResult(
            tools=[_sdk_tool(tools[name]) for name in sorted(tools)],
            ttlMs=300_000,
            cacheScope="private",
        )

    async def call_tool(
        _ctx: ServerRequestContext[Any, Any],
        params: CallToolRequestParams,
    ) -> CallToolResult:
        tool = tools.get(params.name)
        if tool is None:
            raise MCPError(code=METHOD_NOT_FOUND, message=f"unknown tool: {params.name}")
        arguments = params.arguments or {}
        if not isinstance(arguments, dict):
            raise MCPError(code=INVALID_PARAMS, message="arguments must be an object")
        result = await _invoke(tool, arguments)
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
            structuredContent=result,
            isError=result["status"] == "error",
        )

    server = Server(
        SERVICE_NAME,
        version=API_VERSION,
        description="Google Workspace and NotebookLM tools.",
        instructions="Use the narrowest Workspace tool. Read before write and never infer missing data.",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
    mcp_url = os.getenv("MW_MCP_CLIENT_URL", DEFAULT_MCP_URL).strip() or DEFAULT_MCP_URL
    parsed = urlsplit(mcp_url)
    issuer = f"{parsed.scheme}://{parsed.netloc}"
    mode = auth_mode()
    profile = os.getenv("MW_PROFILE", "readonly")
    oauth_provider = None
    auth_server_provider = None
    custom_routes = None
    if mode == "oauth":
        required_scopes = active_mcp_scopes(profile)
        oauth_provider = LocalGoogleOAuthProvider(
            issuer=issuer,
            resource=mcp_url,
            profile=profile,
        )
        token_verifier = ProviderTokenVerifier(oauth_provider)
        auth_server_provider = oauth_provider
        custom_routes = [
            Route(
                "/oauth/google/callback",
                endpoint=oauth_provider.handle_google_callback,
                methods=["GET"],
            )
        ]
        registration_options = ClientRegistrationOptions(
            enabled=True,
            valid_scopes=required_scopes,
            default_scopes=required_scopes,
        )
        revocation_options = RevocationOptions(enabled=True)
    else:
        required_scopes = []
        token_verifier = WorkspaceTokenVerifier()
        registration_options = None
        revocation_options = None
    allowed_hosts = {
        "testserver",
        "localhost",
        "localhost:*",
        "127.0.0.1",
        "127.0.0.1:*",
        parsed.netloc,
        *(item.strip() for item in os.getenv("MW_MCP_ALLOWED_HOSTS", "").split(",") if item.strip()),
    }
    allowed_origins = {
        issuer,
        "http://localhost:*",
        "http://127.0.0.1:*",
        *(item.strip() for item in os.getenv("MW_MCP_ALLOWED_ORIGINS", "").split(",") if item.strip()),
    }
    application = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        max_request_body_size=1_048_576,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=sorted(allowed_hosts),
            allowed_origins=sorted(allowed_origins),
        ),
        host="0.0.0.0",
        auth=AuthSettings(
            issuer_url=issuer,
            resource_server_url=mcp_url,
            required_scopes=required_scopes,
            client_registration_options=registration_options,
            revocation_options=revocation_options,
        ),
        token_verifier=token_verifier,
        auth_server_provider=auth_server_provider,
        custom_starlette_routes=custom_routes,
    )
    application.state.auth_mode = mode
    application.state.oauth_provider = oauth_provider
    return application


def create_app() -> FastAPI:
    tools = load_tools()
    mcp_app = create_mcp_app(tools)

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    application = FastAPI(title=SERVICE_NAME, version=API_VERSION, lifespan=lifespan)

    @application.get("/healthz")
    def healthz() -> dict[str, Any]:
        oauth_provider = mcp_app.state.oauth_provider
        auth_status = (
            {
                "configured": oauth_provider.configured,
                "google_connected": oauth_provider.google_connected,
                "type": "oauth",
            }
            if oauth_provider is not None
            else {"configured": api_key_configured(), "type": "api_key"}
        )
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "version": API_VERSION,
            "profile": os.getenv("MW_PROFILE", "readonly"),
            "tools_count": len(tools),
            "plugin_id": PLUGIN_SPEC.plugin_id,
            "auth": auth_status,
        }

    @application.get("/schema")
    def schema() -> dict[str, Any]:
        return {
            "service": SERVICE_NAME,
            "version": API_VERSION,
            "tools": [
                {
                    "name": tool.name,
                    "plugin_id": tool.plugin_id,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                    "mutates_state": bool(tool.mutates_state),
                    "required_capability": tool.required_capability,
                }
                for tool in sorted(tools.values(), key=lambda item: item.name)
            ],
        }

    application.mount("/", mcp_app)
    application.state.tools = tools
    return application


app = create_app()
