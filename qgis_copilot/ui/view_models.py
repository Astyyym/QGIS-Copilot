"""Presentation models for the transparent QGIS Copilot workbench."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ChatState(str, Enum):
    EMPTY = "empty"
    SENDING = "sending"
    READY = "ready"
    ERROR = "error"
    CANCELLED = "cancelled"


class WorkbenchStage(str, Enum):
    READY = "ready"
    MODEL_ANALYSIS = "model_analysis"
    READING_PROJECT = "reading_project"
    CALLING_TOOL = "calling_tool"
    WAITING_CONFIRMATION = "waiting_confirmation"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ResultAction:
    """A user-clicked, main-thread QGIS action attached to a real result."""

    kind: str
    label: str
    target: str


@dataclass(frozen=True)
class ToolCard:
    title: str
    summary: str
    detail: str
    status: str = "completed"
    actions: tuple[ResultAction, ...] = ()


@dataclass(frozen=True)
class AuditEntry:
    stage: str
    detail: str
    duration_ms: int | None = None


@dataclass
class ChatViewModel:
    state: ChatState = ChatState.EMPTY
    messages: list[ChatMessage] | None = None
    cards: list[ToolCard] | None = None

    def __post_init__(self):
        if self.messages is None:
            self.messages = []
        if self.cards is None:
            self.cards = []

    def add_message(self, role: str, content: str) -> ChatMessage:
        message = ChatMessage(role=role, content=content)
        self.messages.append(message)
        return message
