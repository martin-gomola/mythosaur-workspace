from __future__ import annotations

import asyncio
import ipaddress
import os
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Literal, NamedTuple, Protocol, TypeAlias
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

JsonDict: TypeAlias = dict[str, Any]


class ToolErrorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: JsonDict | None = None


class ToolResultMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    duration_ms: int = Field(ge=0)
    source: str


class ToolResultEnvelope(BaseModel):
    """Canonical typed result shared by plugins, MCP, and catalog clients."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "error"]
    tool: str
    data: JsonDict
    error: ToolErrorPayload | None
    meta: ToolResultMeta

    @model_validator(mode="after")
    def validate_status_error_pair(self) -> ToolResultEnvelope:
        if self.status == "ok" and self.error is not None:
            raise ValueError("successful tool results cannot contain an error")
        if self.status == "error" and self.error is None:
            raise ValueError("failed tool results must contain an error")
        return self


class SyncHandler(Protocol):
    def __call__(self, args: JsonDict, /) -> JsonDict: ...


class AsyncHandler(Protocol):
    async def __call__(self, args: JsonDict, /) -> JsonDict: ...


Handler: TypeAlias = SyncHandler | AsyncHandler
RuntimeState: TypeAlias = tuple[JsonDict | None, JsonDict | None]
RuntimeStateProvider: TypeAlias = Callable[[bool], RuntimeState]
READONLY_PROFILE: Final = "readonly"
POWER_PROFILE: Final = "power"
TRUE_ENV_VALUES: Final = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class ToolPolicy:
    """Agent-facing routing metadata owned by the plugin that declares a tool."""

    category: str | None = None
    required_capability: str | None = None
    entity_type: str | None = None
    exposure: str | None = None
    latency_hint: str | None = None
    use_when: str | None = None
    avoid_when: str | None = None
    success_next: tuple[str, ...] = ()
    fallback_tools: tuple[str, ...] = ()
    retryable_error_codes: tuple[str, ...] = ()

    def merge(self, other: ToolPolicy | None) -> ToolPolicy:
        if other is None:
            return self
        return ToolPolicy(
            category=other.category or self.category,
            required_capability=other.required_capability or self.required_capability,
            entity_type=other.entity_type or self.entity_type,
            exposure=other.exposure or self.exposure,
            latency_hint=other.latency_hint or self.latency_hint,
            use_when=other.use_when or self.use_when,
            avoid_when=other.avoid_when or self.avoid_when,
            success_next=other.success_next or self.success_next,
            fallback_tools=other.fallback_tools or self.fallback_tools,
            retryable_error_codes=other.retryable_error_codes or self.retryable_error_codes,
        )


@dataclass(frozen=True)
class PluginSpec:
    """Plugin-owned catalog, routing, and runtime-readiness declaration."""

    plugin_id: str
    capability_group: str
    access_mode: str = "read"
    default_category: str | None = None
    recommended_prefixes: tuple[str, ...] = ("/tools",)
    native_preferred: bool = False
    runtime_state: RuntimeStateProvider | None = None
    tool_policies: dict[str, ToolPolicy] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.access_mode not in {"read", "write", "mixed"}:
            raise ValueError(
                f"plugin {self.plugin_id!r} has invalid access_mode {self.access_mode!r}"
            )

    def bind(self, tool: ToolDef) -> ToolDef:
        if tool.plugin_id and tool.plugin_id != self.plugin_id:
            raise ValueError(
                f"tool {tool.name!r} declares plugin_id {tool.plugin_id!r}; "
                f"expected {self.plugin_id!r}"
            )
        bound = replace(
            tool,
            plugin_id=self.plugin_id,
            plugin_spec=self,
            policy=(tool.policy or ToolPolicy()).merge(self.tool_policies.get(tool.name)),
        )
        if bound.mutates_state is None:
            raise ValueError(
                f"tool {bound.name!r} must declare mutation behavior through a read/write builder"
            )
        if bound.mutates_state and self.access_mode == "read":
            raise ValueError(
                f"mutating tool {bound.name!r} cannot belong to read-only plugin {self.plugin_id!r}"
            )
        if bound.mutates_state and not bound.audit_action:
            raise ValueError(f"mutating tool {bound.name!r} requires audit_action")
        return bound


@dataclass
class ToolDef:
    name: str
    plugin_id: str
    description: str
    input_schema: JsonDict
    handler: Handler
    aliases: list[str] | None = None
    is_async: bool = False
    category: str | None = None
    required_capability: str | None = None
    audit_action: str | None = None
    mutates_state: bool | None = None
    destructive: bool = False
    emits_event: bool | None = None
    mutation_event: str | None = None
    entity_type: str | None = None
    plugin_spec: PluginSpec | None = None
    policy: ToolPolicy | None = None

    async def invoke(self, args: JsonDict) -> JsonDict:
        if self.mutates_state and is_readonly():
            return err(
                self.name,
                "readonly",
                f"{self.name} is blocked in readonly profile",
                self.plugin_id,
                now_ms(),
            )
        if self.is_async:
            return await self.handler(args)
        return await asyncio.to_thread(self.handler, args)


def read_tool(
    *,
    name: str,
    plugin_id: str,
    description: str,
    input_schema: JsonDict,
    handler: Handler,
    category: str,
    required_capability: str | None = None,
    aliases: list[str] | None = None,
    is_async: bool = False,
    entity_type: str | None = None,
    policy: ToolPolicy | None = None,
) -> ToolDef:
    return ToolDef(
        name=name,
        plugin_id=plugin_id,
        description=description,
        input_schema=input_schema,
        handler=handler,
        aliases=aliases,
        is_async=is_async,
        category=category,
        required_capability=required_capability,
        mutates_state=False,
        entity_type=entity_type,
        policy=policy,
    )


def write_tool(
    *,
    name: str,
    plugin_id: str,
    description: str,
    input_schema: JsonDict,
    handler: Handler,
    category: str,
    audit_action: str,
    destructive: bool = False,
    required_capability: str | None = None,
    aliases: list[str] | None = None,
    is_async: bool = False,
    emits_event: bool | None = None,
    mutation_event: str | None = None,
    entity_type: str | None = None,
    policy: ToolPolicy | None = None,
) -> ToolDef:
    if not audit_action:
        raise ValueError(f"write_tool {name!r} requires audit_action")
    return ToolDef(
        name=name,
        plugin_id=plugin_id,
        description=description,
        input_schema=input_schema,
        handler=handler,
        aliases=aliases,
        is_async=is_async,
        category=category,
        required_capability=required_capability,
        audit_action=audit_action,
        mutates_state=True,
        destructive=destructive,
        emits_event=emits_event,
        mutation_event=mutation_event,
        entity_type=entity_type,
        policy=policy,
    )


class PluginToolset(NamedTuple):
    read: Callable[..., ToolDef]
    write: Callable[..., ToolDef]


def plugin_toolset(plugin: PluginSpec) -> PluginToolset:
    """Return read/write ToolDef builders bound to one plugin declaration."""

    def _category(category: str | None) -> str:
        return category or plugin.default_category or plugin.capability_group

    def read(
        *,
        name: str,
        description: str,
        handler: Handler,
        input_schema: JsonDict | None = None,
        category: str | None = None,
        required_capability: str | None = None,
        aliases: list[str] | None = None,
        is_async: bool = False,
        entity_type: str | None = None,
        policy: ToolPolicy | None = None,
    ) -> ToolDef:
        tool = read_tool(
            name=name,
            plugin_id=plugin.plugin_id,
            description=description,
            input_schema=deepcopy(input_schema or {"type": "object", "properties": {}}),
            handler=handler,
            category=_category(category),
            required_capability=required_capability,
            aliases=aliases,
            is_async=is_async,
            entity_type=entity_type,
            policy=policy,
        )
        return plugin.bind(tool)

    def write(
        *,
        name: str,
        description: str,
        handler: Handler,
        audit_action: str,
        destructive: bool = False,
        input_schema: JsonDict | None = None,
        category: str | None = None,
        required_capability: str | None = None,
        aliases: list[str] | None = None,
        is_async: bool = False,
        emits_event: bool | None = None,
        mutation_event: str | None = None,
        entity_type: str | None = None,
        policy: ToolPolicy | None = None,
    ) -> ToolDef:
        tool = write_tool(
            name=name,
            plugin_id=plugin.plugin_id,
            description=description,
            input_schema=deepcopy(input_schema or {"type": "object", "properties": {}}),
            handler=handler,
            category=_category(category),
            audit_action=audit_action,
            destructive=destructive,
            required_capability=required_capability,
            aliases=aliases,
            is_async=is_async,
            emits_event=emits_event,
            mutation_event=mutation_event,
            entity_type=entity_type,
            policy=policy,
        )
        return plugin.bind(tool)

    return PluginToolset(read=read, write=write)


def scope_check(granted: bool, *, reason: str = "", missing_scopes: list[str] | None = None) -> JsonDict:
    payload: JsonDict = {"granted": bool(granted), "missing_scopes": list(missing_scopes or [])}
    if reason:
        payload["reason"] = reason
    return payload


def local_runtime_state(readonly: bool, capabilities: tuple[str, ...]) -> RuntimeState:
    granted = {name: not readonly if name.endswith("_write") else True for name in capabilities}
    return (
        granted,
        {
            "mode": "local",
            "configured": True,
            "token_present": False,
            "scope_checks": {
                name: scope_check(
                    enabled,
                    reason="" if enabled else f"MW_PROFILE=power required for {name}",
                )
                for name, enabled in granted.items()
            },
            "service_checks": {"readonly_profile": readonly} if readonly else {},
        },
    )


def now_ms() -> int:
    return int(time.time() * 1000)


def _meta(source: str, started_ms: int) -> JsonDict:
    return {
        "duration_ms": max(0, now_ms() - started_ms),
        "source": source,
    }


def ok(tool: str, data: JsonDict, source: str, started_ms: int) -> JsonDict:
    return ToolResultEnvelope.model_validate(
        {
            "status": "ok",
            "tool": tool,
            "data": data,
            "error": None,
            "meta": _meta(source, started_ms),
        }
    ).model_dump(mode="json")


def err(
    tool: str,
    code: str,
    message: str,
    source: str,
    started_ms: int,
    details: JsonDict | None = None,
) -> JsonDict:
    error: JsonDict = {"code": code, "message": message}
    if details:
        error["details"] = details
    return ToolResultEnvelope.model_validate(
        {
            "status": "error",
            "tool": tool,
            "data": {},
            "error": error,
            "meta": _meta(source, started_ms),
        }
    ).model_dump(mode="json")


def parse_int(value: Any, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        out = default
    if minimum is not None:
        out = max(minimum, out)
    if maximum is not None:
        out = min(maximum, out)
    return out


def env_get(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value is not None and value != "" else default


def repo_root() -> Path:
    """Mythosaur-tools repo root inside the container (mounted at /app)."""
    raw = (env_get("MW_REPO_ROOT", "/app") or "/app").strip() or "/app"
    return Path(raw).resolve()


def shared_root() -> Path:
    """Shared files directory for uploads/downloads (mounted at /shared)."""
    raw = (env_get("MW_SHARED_ROOT", "/shared") or "/shared").strip() or "/shared"
    return Path(raw).resolve()


def _resolve_path_under(path_value: str, base: Path, escape_message: str) -> Path:
    value = (path_value or "").strip()
    if not value:
        raise ValueError("path is required")
    if "\x00" in value:
        raise ValueError("path contains NUL byte")

    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = base / candidate

    resolved = candidate.resolve(strict=False)
    if resolved == base:
        return resolved

    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError(escape_message.format(path_value=path_value)) from exc
    return resolved


def resolve_under_repo(path_value: str) -> Path:
    return _resolve_path_under(
        path_value,
        repo_root(),
        "path escapes repo root: {path_value}",
    )


def resolve_under_shared(path_value: str) -> Path:
    return _resolve_path_under(
        path_value,
        shared_root(),
        "path escapes shared dir: {path_value}",
    )


def resolve_under_base(path_value: str, base_dir: str | Path) -> Path:
    return _resolve_path_under(
        path_value,
        Path(base_dir).resolve(),
        "path escapes base dir: {path_value}",
    )


_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def validate_fetch_url(url: str) -> None:
    """Reject URLs with non-http(s) schemes or targeting private/reserved addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme not allowed: {parsed.scheme!r} (only http and https)")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("URL has no hostname")
    if hostname in ("localhost", "localhost.localdomain"):
        raise ValueError("localhost URLs are not allowed")

    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        return  # non-IP hostname (domain name) is fine
    for net in _BLOCKED_NETWORKS:
        if addr in net:
            raise ValueError(f"URL targets a blocked private/reserved network: {addr}")


def command_profile() -> str:
    return (env_get("MW_PROFILE", READONLY_PROFILE) or READONLY_PROFILE).strip().lower() or READONLY_PROFILE


def is_readonly() -> bool:
    return command_profile() != POWER_PROFILE


def bool_env(name: str, default: bool = False) -> bool:
    """Parse a boolean from an environment variable (1, true, yes, on)."""
    raw = (env_get(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in TRUE_ENV_VALUES


def listify_strings(value: Any) -> list[str]:
    """Convert a string (comma-separated), list, or single value to a list of non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


# ---------------------------------------------------------------------------
#  Domain exceptions — caught by centralised error mapping in _invoke_tool
# ---------------------------------------------------------------------------


class ToolError(Exception):
    """Base for tool-domain errors that map to a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class PathGuardError(ToolError):
    """Raised when a path escapes its allowed root."""

    def __init__(self, message: str) -> None:
        super().__init__("path_guard", message)


class ReadonlyError(ToolError):
    """Raised when a mutation is attempted in readonly profile."""

    def __init__(self, tool_name: str) -> None:
        super().__init__("readonly", f"{tool_name} is blocked in readonly profile")


class ConfirmRequired(ToolError):
    """Raised when a destructive action is missing ``confirm=true``."""

    def __init__(self, tool_name: str, action: str) -> None:
        super().__init__(
            "confirm_required",
            f"{tool_name}: {action} requires confirm=true",
        )


class NotConfiguredError(ToolError):
    """Raised when a backing service is not configured."""

    def __init__(self, service: str) -> None:
        super().__init__("not_configured", f"{service} is not configured")


# ---------------------------------------------------------------------------
#  Safety-gate helpers
# ---------------------------------------------------------------------------


def require_confirm(tool_name: str, args: JsonDict, action: str) -> None:
    """Raise :class:`ConfirmRequired` unless ``confirm`` is truthy."""
    raw = args.get("confirm")
    if isinstance(raw, bool) and raw:
        return
    if isinstance(raw, str) and raw.strip().lower() in TRUE_ENV_VALUES:
        return
    raise ConfirmRequired(tool_name, action)


def check_dry_run(args: JsonDict) -> bool:
    """Return *True* when the caller wants a dry-run (the default)."""
    raw = args.get("dry_run")
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}
