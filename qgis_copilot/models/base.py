"""Provider contract kept independent of Qt widgets and PyQGIS objects."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class ModelRequestError(RuntimeError):
    """A safe, user-displayable failure from a model provider."""


class ModelAuthenticationError(ModelRequestError):
    """The model endpoint rejected the supplied credentials."""


class ModelTimeoutError(ModelRequestError):
    """The model endpoint did not answer before the configured deadline."""


class ModelCancelledError(ModelRequestError):
    """The user cancelled the request before a result was accepted."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ChatCompletion:
    content: str
    model: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()


class ModelAdapter(ABC):
    """Minimal synchronous contract executed by the background network worker."""

    @abstractmethod
    def complete(self, messages: list[dict], cancel_event, tools: list[dict] | None = None) -> ChatCompletion:
        """Return one assistant completion or raise a typed request error."""
