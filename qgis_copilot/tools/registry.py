"""In-process registry for validated, high-level QGIS tools."""
from __future__ import annotations

from typing import Any

from .contracts import ToolResult, ToolSpec
from .permissions import can_execute


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if not spec.name or spec.name in self._tools:
            raise ValueError(f"invalid or duplicate tool: {spec.name!r}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def discover(self) -> list[dict[str, Any]]:
        return [self._tools[name].public_schema() for name in sorted(self._tools)]

    def call(self, name: str, arguments: dict[str, Any] | None = None, *, confirmed: bool = False) -> ToolResult:
        spec = self.get(name)
        if spec is None:
            return ToolResult(name, False, {}, "工具不存在。")
        # Write-class tools in this registry only create a validated plan. The actual
        # Processing side effect is owned by BufferProcessingTask after UI confirmation.
        if not can_execute(spec, confirmed=confirmed) and spec.permission.value != "write":
            return ToolResult(name, False, {}, "工具需要用户确认。")
        try:
            data = spec.handler(arguments or {})
            return ToolResult(name, True, data)
        except (KeyError, TypeError, ValueError) as exc:
            return ToolResult(name, False, {}, f"参数无效：{exc}")
        except Exception as exc:
            return ToolResult(name, False, {}, f"工具执行失败：{exc}")
