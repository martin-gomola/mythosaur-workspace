from __future__ import annotations

import os

from fastapi.testclient import TestClient

from services.mcp_server.app import create_app, load_tools


def run() -> None:
    previous_key = os.environ.get("MW_API_KEY")
    previous_auth_mode = os.environ.get("MW_MCP_AUTH_MODE")
    previous_profile = os.environ.get("MW_PROFILE")
    os.environ["MW_API_KEY"] = "test-workspace-key"
    os.environ["MW_MCP_AUTH_MODE"] = "api_key"
    os.environ["MW_PROFILE"] = "readonly"
    try:
        tools = load_tools()
        assert len(tools) == 34
        assert {tool.plugin_id for tool in tools.values()} == {"mythosaur.google_workspace"}
        assert "google_calendar_events" in tools
        assert "notebooklm_query_notebook" in tools
        assert "search_memory" not in tools

        with TestClient(create_app()) as client:
            health = client.get("/healthz")
            assert health.status_code == 200
            assert health.json()["tools_count"] == 34
            assert health.json()["auth"] == {"configured": True, "type": "api_key"}

            schema = client.get("/schema")
            assert schema.status_code == 200
            schema_tools = schema.json()["tools"]
            assert len(schema_tools) == 34
            assert {tool["plugin_id"] for tool in schema_tools} == {
                "mythosaur.google_workspace"
            }

            request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
            unauthorized = client.post("/mcp", json=request)
            assert unauthorized.status_code == 401

            headers = {"Authorization": "Bearer test-workspace-key"}
            response = client.post("/mcp", json=request, headers=headers)
            assert response.status_code == 200, response.text
            listed_tools = response.json()["result"]["tools"]
            assert len(listed_tools) == 34
            assert {
                tool["_meta"]["io.mythosaur/tool"]["pluginId"]
                for tool in listed_tools
            } == {"mythosaur.google_workspace"}

            mutation = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "google_calendar_create_event",
                        "arguments": {},
                    },
                },
                headers=headers,
            )
            assert mutation.status_code == 200, mutation.text
            result = mutation.json()["result"]["structuredContent"]
            assert result["status"] == "error"
            assert result["error"]["code"] == "readonly"
    finally:
        if previous_key is None:
            os.environ.pop("MW_API_KEY", None)
        else:
            os.environ["MW_API_KEY"] = previous_key
        if previous_auth_mode is None:
            os.environ.pop("MW_MCP_AUTH_MODE", None)
        else:
            os.environ["MW_MCP_AUTH_MODE"] = previous_auth_mode
        if previous_profile is None:
            os.environ.pop("MW_PROFILE", None)
        else:
            os.environ["MW_PROFILE"] = previous_profile
    print("runtime smoke: 34 Workspace tools, auth enforced, readonly mutation blocked")


if __name__ == "__main__":
    run()
