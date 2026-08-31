"""Bounded OpenAI-compatible conversation, including tool protocol messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Conversation:
    """Keeps a bounded sequence acceptable to an OpenAI-compatible API."""

    max_messages: int = 30
    _messages: list[dict[str, Any]] = field(default_factory=list)

    def add(self, role: str, content: str | None = None, **fields: Any) -> None:
        if role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"不支持的会话角色：{role}")
        message: dict[str, Any] = {"role": role}
        if content is not None:
            if not isinstance(content, str):
                raise ValueError("会话文本必须是字符串。")
            message["content"] = content.strip()
        if role in {"system", "user"} and not message.get("content"):
            raise ValueError("会话消息不能为空。")
        if role == "assistant" and not message.get("content") and not fields.get("tool_calls"):
            raise ValueError("assistant 消息必须包含文本或工具调用。")
        if role == "tool":
            if not message.get("content") or not isinstance(fields.get("tool_call_id"), str) or not fields["tool_call_id"]:
                raise ValueError("工具结果必须包含内容和 tool_call_id。")
        message.update(fields)
        self._messages.append(message)
        self._messages = self._messages[-self.max_messages:]

    def request_messages(self) -> list[dict[str, Any]]:
        return [dict(message) for message in self._messages]

    def current_tool_turn_messages(self) -> list[dict[str, Any]]:
        """Keep only the current request and tool exchange for the next model turn."""
        system = next((message for message in self._messages if message["role"] == "system"), None)
        user_index = max((index for index, message in enumerate(self._messages) if message["role"] == "user"), default=-1)
        if user_index < 0:
            raise ValueError("当前会话没有用户问题。")
        messages = ([dict(system)] if system else []) + [dict(message) for message in self._messages[user_index:] if not (message["role"] == "system" and message.get("content", "").startswith("当前 QGIS 上下文："))]
        return messages

    def reset(self) -> None:
        """Start a fresh conversation while retaining no prior user/tool history."""
        self._messages.clear()
