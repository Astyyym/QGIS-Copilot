"""Permission checks for the built-in tool registry."""

from .contracts import PermissionLevel, ToolSpec


_CONFIRMATION_REQUIRED = {PermissionLevel.WRITE, PermissionLevel.DESTRUCTIVE, PermissionLevel.CODE_EXECUTION}


def is_read_only(tool: ToolSpec) -> bool:
    return tool.permission == PermissionLevel.READ_ONLY


def requires_confirmation(tool: ToolSpec) -> bool:
    return tool.permission in _CONFIRMATION_REQUIRED


def can_execute(tool: ToolSpec, *, confirmed: bool = False) -> bool:
    return is_read_only(tool) or (requires_confirmation(tool) and confirmed)
