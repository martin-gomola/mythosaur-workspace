from __future__ import annotations

from typing import Final

from ..common import ToolDef
from .google_tools import get_tools as _google_tools
from .notebooklm import get_tools as _notebooklm_tools
from .google_plugin import PLUGIN_SPEC as PLUGIN_SPEC  # noqa: F401 - plugin discovery reads module metadata

TOOL_GROUP_LOADERS: Final = (
    _google_tools,
    _notebooklm_tools,
)


def get_tools() -> list[ToolDef]:
    tools: list[ToolDef] = []
    for loader in TOOL_GROUP_LOADERS:
        tools.extend(loader())
    return tools
