"""Google Workspace MCP tool handlers grouped by service."""

from __future__ import annotations

from typing import Final

from ...common import ToolDef
from ._calendar import get_tools as _calendar_tools
from ._docs import get_tools as _docs_tools
from ._drive import get_tools as _drive_tools
from ._gmail import get_tools as _gmail_tools
from ._maps import get_tools as _maps_tools
from ._photos import get_tools as _photos_tools
from ._sheets import get_tools as _sheets_tools

TOOL_GROUP_LOADERS: Final = (
    _calendar_tools,
    _gmail_tools,
    _drive_tools,
    _sheets_tools,
    _docs_tools,
    _photos_tools,
    _maps_tools,
)


def get_tools() -> list[ToolDef]:
    tools: list[ToolDef] = []
    for loader in TOOL_GROUP_LOADERS:
        tools.extend(loader())
    return tools
