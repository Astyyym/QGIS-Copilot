"""Stable contracts for native QGIS tools and confirmed write plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class PermissionLevel(str, Enum):
    READ_ONLY = "read_only"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    CODE_EXECUTION = "code_execution"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    permission: PermissionLevel
    handler: Callable[[dict[str, Any]], dict[str, Any]]
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}, "additionalProperties": False})

    def public_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
            "permission": self.permission.value,
        }


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    ok: bool
    data: dict[str, Any]
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        result = {"tool": self.tool_name, "ok": self.ok, "data": self.data}
        if self.error:
            result["error"] = self.error
        return result


@dataclass(frozen=True)
class ExecutionPlan:
    """Validated but not yet executed write operation shown to the user."""

    tool_name: str
    title: str
    inputs: dict[str, Any]
    parameters: dict[str, Any]
    output_path: str
    output_layer_name: str
    impact: str
    risks: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool_name,
            "title": self.title,
            "inputs": self.inputs,
            "parameters": self.parameters,
            "output_path": self.output_path,
            "output_layer_name": self.output_layer_name,
            "impact": self.impact,
            "risks": list(self.risks),
        }
