"""Structured events emitted from the Agent loop to the application layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AgentEventType(str, Enum):
    STARTED = "started"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class AgentEvent:
    type: AgentEventType
    detail: str = ""
    content: str = ""
    tool_name: str = ""
