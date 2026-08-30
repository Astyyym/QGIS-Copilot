"""Model-independent bounded tool-aware Agent loop."""

from __future__ import annotations

import json

from .conversation import Conversation
from .events import AgentEvent, AgentEventType
from qgis_copilot.models.base import ChatCompletion, ToolCall


class AgentCore:
    """Own plain-Python conversation state; QGIS work stays in the controller."""

    def __init__(self, system_prompt: str, max_steps: int = 3, tool_registry=None):
        if max_steps < 1:
            raise ValueError("Agent 最大步数至少为 1。")
        self._system_prompt = system_prompt
        self._max_steps = max_steps
        self._steps = 0
        self._conversation = Conversation()
        self._conversation.add("system", system_prompt)
        self.tool_registry = tool_registry

    @property
    def steps(self):
        return self._steps

    @property
    def max_steps(self):
        return self._max_steps

    def begin(self, user_text: str, context: dict | None = None) -> list[dict]:
        self._add_model_turn()
        self._conversation.add("user", user_text)
        if context:
            self._conversation.add("system", "当前 QGIS 上下文：" + json.dumps(context, ensure_ascii=False, default=str))
        return self._conversation.request_messages()

    def next_model_request(self) -> list[dict]:
        self._add_model_turn()
        return self._conversation.current_tool_turn_messages()

    def accept_completion(self, completion: ChatCompletion) -> None:
        tool_calls = [
            {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)}}
            for call in completion.tool_calls
        ]
        self._conversation.add("assistant", completion.content or None, tool_calls=tool_calls or None)

    def accept_tool_result(self, tool_call: ToolCall, result) -> None:
        self._conversation.add(
            "tool", json.dumps(result.as_dict(), ensure_ascii=False, default=str),
            tool_call_id=tool_call.id,
            name=tool_call.name,
        )

    def reset_request_budget(self) -> None:
        self._steps = 0

    def _add_model_turn(self) -> None:
        if self._steps >= self._max_steps:
            raise RuntimeError("已达到本次请求的最大调用步数，未继续请求模型。")
        self._steps += 1

    def tool_event(self, tool_name: str, arguments: dict) -> AgentEvent:
        if self.tool_registry is None:
            return AgentEvent(AgentEventType.FAILED, "未配置工具注册表。", tool_name=tool_name)
        if not isinstance(arguments, dict):
            return AgentEvent(AgentEventType.FAILED, "工具参数必须是对象。", tool_name=tool_name)
        return AgentEvent(AgentEventType.TOOL_STARTED, "开始调用已注册工具。", tool_name=tool_name)

    def execute_tool(self, tool_name: str, arguments: dict):
        event = self.tool_event(tool_name, arguments)
        if event.type == AgentEventType.FAILED:
            return event, None
        result = self.tool_registry.call(tool_name, arguments)
        if not result.ok:
            return AgentEvent(AgentEventType.FAILED, result.error, tool_name=tool_name), result
        return AgentEvent(AgentEventType.TOOL_COMPLETED, json.dumps(result.as_dict(), ensure_ascii=False, default=str), tool_name=tool_name), result
