"""OpenAI-compatible HTTP adapter using only the Python standard library."""

from __future__ import annotations

import json
from urllib import error, request

from .base import (
    ChatCompletion,
    ModelAdapter,
    ModelAuthenticationError,
    ModelCancelledError,
    ModelRequestError,
    ModelTimeoutError,
    ToolCall,
)
from .request_options import build_request_options
from .settings import ModelSettings
from qgis_copilot.security.redaction import redact_text


class OpenAICompatibleAdapter(ModelAdapter):
    """Make a single chat/completions request; call only from a worker thread."""

    def __init__(self, settings: ModelSettings, api_key: str):
        self._settings = settings.validate()
        self._api_key = api_key

    def complete(self, messages: list[dict], cancel_event, tools: list[dict] | None = None) -> ChatCompletion:
        if cancel_event.is_set():
            raise ModelCancelledError("请求已取消。")
        request_body = {
            "model": self._settings.model_name,
            "messages": messages,
            "stream": False,
            **build_request_options(
                self._settings.capability_profile,
                self._settings.resolved_behavior_mode,
            ),
        }
        if tools:
            request_body["tools"] = tools
            request_body["tool_choice"] = "auto"
        payload = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
        http_request = request.Request(
            self._settings.chat_completions_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self._settings.timeout_seconds) as response:
                raw_response = response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code in {401, 403}:
                raise ModelAuthenticationError("模型服务拒绝了认证信息（HTTP %s）。" % exc.code) from exc
            raise ModelRequestError(
                "模型服务返回 HTTP %s：%s" % (exc.code, redact_text(detail))
            ) from exc
        except error.URLError as exc:
            reason = redact_text(exc.reason)
            if "timed out" in str(reason).lower():
                raise ModelTimeoutError("模型服务连接超时。") from exc
            raise ModelRequestError(f"无法连接模型服务：{reason}") from exc
        except TimeoutError as exc:
            raise ModelTimeoutError("模型服务请求超时。") from exc

        if cancel_event.is_set():
            raise ModelCancelledError("请求已取消；已丢弃模型响应。")
        try:
            data = json.loads(raw_response)
            message = data["choices"][0]["message"]
            content = message.get("content") or ""
            tool_calls = []
            for call in message.get("tool_calls", []):
                function = call["function"]
                arguments = function.get("arguments", {})
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if not isinstance(arguments, dict):
                    raise TypeError("tool arguments must be an object")
                tool_calls.append(ToolCall(str(call.get("id", "")), function["name"], arguments))
        except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ModelRequestError("模型服务返回了无法识别的响应。") from exc
        if not isinstance(content, str) or (not content.strip() and not tool_calls):
            raise ModelRequestError("模型服务没有返回可显示的文本或工具调用。")
        return ChatCompletion(content=content.strip(), model=data.get("model"), tool_calls=tuple(tool_calls))
