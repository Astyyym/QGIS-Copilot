"""Small presentation models shared by the chat UI and controller."""

from dataclasses import dataclass
from enum import Enum


class ChatState(str, Enum):
    EMPTY = "empty"
    SENDING = "sending"
    READY = "ready"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass
class ChatViewModel:
    state: ChatState = ChatState.EMPTY
    messages: list[ChatMessage] | None = None

    def __post_init__(self):
        if self.messages is None:
            self.messages = []

    def add_message(self, role: str, content: str) -> ChatMessage:
        message = ChatMessage(role=role, content=content)
        self.messages.append(message)
        return message
