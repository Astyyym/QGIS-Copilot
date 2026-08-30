"""Connect chat UI, settings, bounded Agent and background model requests."""

from __future__ import annotations

import json

from qgis.PyQt.QtCore import QObject

from qgis_copilot.agent.core import AgentCore
from qgis_copilot.context.project_context import build_model_project_context
from qgis_copilot.diagnostics.logging import DiagnosticsLogger
from qgis_copilot.models.base import ChatCompletion
from qgis_copilot.models.openai_compatible import OpenAICompatibleAdapter
from qgis_copilot.models.settings import ModelSettings, ModelSettingsStore
from qgis_copilot.security.credentials import CredentialStoreError, QgisCredentialStore
from qgis_copilot.security.redaction import redact_text
from qgis_copilot.tasks.network import NetworkRequestThread
from qgis_copilot.tasks.processing import BufferProcessingTask
from qgis_copilot.tools.contracts import PermissionLevel
from qgis_copilot.tools.qgis_tools import create_default_registry
from qgis_copilot.ui.chat_dock import ChatDockWidget
from qgis_copilot.ui.settings_dialog import SettingsDialog
from qgis_copilot.ui.view_models import ChatState, ChatViewModel

_SYSTEM_PROMPT = "你是 QGIS Copilot。只读工具可直接调用。对于用户请求创建矢量缓冲区，只能调用 buffer_vector 生成计划；计划会在界面展示，必须等待用户点击确认后才会执行 Processing。不得请求或声称执行写入、删除、覆盖、保存项目或任意代码。工具返回后必须根据真实结果回答，不能编造。"


def format_timeout_error(detail: str, timeout_seconds: int | None) -> str:
    """Give a visible, non-automatic recovery path after one timed-out request."""
    seconds = timeout_seconds if timeout_seconds is not None else "当前"
    return f"{detail}（当前超时：{seconds} 秒）。可在“设置”中调整超时后点击“重试”；不会自动重复请求。"


class ApplicationController(QObject):
    """Own UI lifecycle and keep all PyQGIS calls on QGIS's main thread."""

    def __init__(self, dock: ChatDockWidget):
        super().__init__(dock)
        self.dock = dock
        self.view_model = ChatViewModel()
        self._active = False
        self._last_message = None
        self._network_thread = None
        self._settings_dialog = None
        self._settings_store = ModelSettingsStore()
        self._credential_store = QgisCredentialStore()
        self._diagnostics = DiagnosticsLogger()
        self.tool_registry = create_default_registry()
        self._agent = AgentCore(_SYSTEM_PROMPT, max_steps=3, tool_registry=self.tool_registry)
        self._adapter = None
        self._active_timeout_seconds = None
        self._pending_plan = None
        self._processing_task = None
        self.dock.message_submitted.connect(self.submit_message)
        self.dock.cancel_requested.connect(self.cancel_request)
        self.dock.retry_requested.connect(self.retry_last_message)
        self.dock.plan_confirmed.connect(self.confirm_pending_plan)
        self.dock.plan_cancelled.connect(self.cancel_pending_plan)
        self.dock.settings_requested.connect(self.show_settings)

    def activate(self):
        self._active = True
        self.dock.set_state(ChatState.READY)

    def deactivate(self):
        self._active = False
        self.cancel_request()
        self.dock.set_state(ChatState.CANCELLED, "插件已关闭，未完成的请求已取消。")

    def submit_message(self, text: str):
        if not self._active or self._network_thread:
            return
        try:
            settings, api_key = self._load_configured_connection()
        except (CredentialStoreError, ValueError) as exc:
            self.dock.set_state(ChatState.ERROR, f"需要模型设置：{redact_text(exc)}")
            self.show_settings()
            return
        self._last_message = text
        self._diagnostics.event("chat_request", status="started", summary={"tool": "agent"})
        self._active_timeout_seconds = settings.timeout_seconds
        self._agent.reset_request_budget()
        self._adapter = OpenAICompatibleAdapter(settings, api_key)
        try:
            messages = self._agent.begin(text, build_model_project_context())
        except (RuntimeError, ValueError) as exc:
            self.dock.set_state(ChatState.ERROR, str(exc))
            return
        self._append("user", text)
        self.dock.set_state(ChatState.SENDING, "正在生成回答…")
        self._start_agent_completion(messages)

    def cancel_request(self):
        if self._network_thread:
            self._network_thread.cancel()
            self.dock.set_state(ChatState.CANCELLED, "正在取消模型请求…")
        elif self._processing_task:
            self._processing_task.cancel()
            self.dock.set_state(ChatState.CANCELLED, "正在取消 GIS Processing 任务…")
        elif self.dock._state == ChatState.SENDING:
            self.dock.set_state(ChatState.CANCELLED, "请求已取消。")

    def retry_last_message(self):
        if self._last_message and not self._network_thread:
            self.submit_message(self._last_message)
            return
        self.dock.set_state(ChatState.ERROR, "没有可重试的请求。请重新输入消息。")

    def show_settings(self):
        if self._settings_dialog:
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        try:
            existing = self._settings_store.load()
        except ValueError:
            existing = None
        dialog = SettingsDialog(existing, self.dock)
        dialog.save_requested.connect(self._save_settings)
        dialog.test_requested.connect(self._test_settings)
        dialog.finished.connect(self._clear_settings_dialog)
        self._settings_dialog = dialog
        dialog.show()

    def _clear_settings_dialog(self, _result):
        self._settings_dialog = None

    def _save_settings(self, settings: ModelSettings, api_key: str):
        try:
            existing = self._settings_store.load()
            auth_config_id = existing.auth_config_id if existing else None
            if api_key.strip():
                auth_config_id = self._credential_store.save_api_key(api_key, auth_config_id)
            if not auth_config_id:
                raise CredentialStoreError("首次保存需要填写 API Key。")
            self._settings_store.save(ModelSettings(settings.base_url, settings.model_name, settings.timeout_seconds, auth_config_id))
        except (CredentialStoreError, ValueError) as exc:
            self._settings_dialog.set_feedback(redact_text(exc), is_error=True)
            return
        self._settings_dialog.set_feedback("已保存：API Key 仅在 QGIS 认证存储中保存。")
        self._settings_dialog.accept()

    def _test_settings(self, settings: ModelSettings, api_key: str):
        try:
            if not api_key.strip():
                existing = self._settings_store.load()
                api_key = self._credential_store.load_api_key(existing.auth_config_id if existing else None)
        except (CredentialStoreError, ValueError) as exc:
            self._settings_dialog.set_feedback(redact_text(exc), is_error=True)
            return
        self._settings_dialog.set_busy("正在测试模型连通性…")
        self._start_completion(
            OpenAICompatibleAdapter(settings, api_key),
            [{"role": "user", "content": "Reply with exactly: connection ok"}],
            on_completed=self._on_connection_test_completed,
            on_failed=self._on_connection_test_failed,
            on_cancelled=self._on_connection_test_cancelled,
        )

    def _on_connection_test_completed(self, _completion):
        if self._settings_dialog:
            self._settings_dialog.set_feedback("模型连通性测试成功。")

    def _on_connection_test_failed(self, detail: str):
        if self._settings_dialog:
            self._settings_dialog.set_feedback(f"连通性测试失败：{detail}", is_error=True)

    def _on_connection_test_cancelled(self):
        if self._settings_dialog:
            self._settings_dialog.set_feedback("连通性测试已取消。", is_error=True)

    def _load_configured_connection(self) -> tuple[ModelSettings, str]:
        settings = self._settings_store.load()
        if settings is None:
            raise ValueError("尚未配置模型地址、模型名和 API Key。")
        return settings, self._credential_store.load_api_key(settings.auth_config_id)

    def _start_agent_completion(self, messages: list[dict]):
        self._start_completion(self._adapter, messages, tools=self.tool_registry.discover())

    def _start_completion(self, adapter, messages, *, tools=None, on_completed=None, on_failed=None, on_cancelled=None):
        thread = NetworkRequestThread(adapter, messages, tools, self)
        self._network_thread = thread
        thread.completed.connect(on_completed or self._on_completion)
        thread.failed.connect(on_failed or self._on_failure)
        thread.cancelled.connect(on_cancelled or self._on_cancelled)
        thread.finished.connect(lambda: self._clear_network_thread(thread))
        thread.start()

    def _clear_network_thread(self, thread):
        if self._network_thread is thread:
            self._network_thread = None
        thread.deleteLater()

    def _on_completion(self, completion: ChatCompletion):
        self._agent.accept_completion(completion)
        if not completion.tool_calls:
            self._append("assistant", completion.content)
            self._diagnostics.event("chat_request", status="success", summary={"has_tool_calls": False})
            self.dock.set_state(ChatState.READY)
            return
        if completion.content:
            self._append("assistant", completion.content)
        for tool_call in completion.tool_calls:
            self._execute_tool_on_main_thread(tool_call)
            if self.dock._state != ChatState.SENDING:
                return
        try:
            self.dock.set_state(ChatState.SENDING, "正在根据工具结果生成回答…")
            self._start_agent_completion(self._agent.next_model_request())
        except RuntimeError as exc:
            self._on_failure(str(exc))

    def _execute_tool_on_main_thread(self, tool_call):
        """Run safe reads now; show write plans and wait for an explicit UI confirmation."""
        spec = self.tool_registry.get(tool_call.name)
        if spec is None:
            self._on_failure(f"工具调用失败：工具不存在（{tool_call.name}）。")
            return
        self.dock.set_state(ChatState.SENDING, f"正在准备工具：{tool_call.name}…")
        with self._diagnostics.timed(f"tool:{tool_call.name}") as diagnostic:
            event, result = self._agent.execute_tool(tool_call.name, tool_call.arguments)
            if result is None or not result.ok:
                diagnostic.failure(event.detail if result is None else result.error)
            else:
                diagnostic.success({"tool": tool_call.name, "ok": True})
        if result is None or not result.ok:
            # A rejected tool call is still a completed protocol event. Preserve the
            # structured failure with the original ID before showing the UI error;
            # otherwise the next user turn resends an orphaned assistant call and
            # strict providers reject it with HTTP 400.
            if result is not None:
                self._agent.accept_tool_result(tool_call, result)
            detail = event.detail if result is None else result.error
            self._append("error", f"工具调用失败（{tool_call.name}）：{detail}")
            self.dock.set_state(ChatState.ERROR, f"工具调用失败：{detail}")
            return
        if spec.permission == PermissionLevel.WRITE:
            # The provider has already returned an assistant tool_call. Persist a
            # matching *plan-only* tool result before pausing for UI confirmation;
            # otherwise a later user message replays an orphaned function call and
            # strict OpenAI-compatible providers correctly reject it with HTTP 400.
            self._agent.accept_tool_result(tool_call, result)
            self._pending_plan = result.data
            self.dock.show_execution_plan(result.data)
            self.dock.set_state(ChatState.READY, "已生成执行计划；请核对影响与输出路径后确认或取消。")
            self._append("tool", f"已生成待确认计划：{result.data['title']}。尚未创建文件或添加图层。")
            return
        self._agent.accept_tool_result(tool_call, result)
        summary = self._tool_summary(result.as_dict())
        self._append("tool", f"工具完成：{tool_call.name}。{summary}")
        self.dock.set_state(ChatState.SENDING, f"工具完成：{tool_call.name}。正在继续…")

    def confirm_pending_plan(self):
        if not self._pending_plan or self._processing_task:
            return
        self.dock.set_plan_controls_enabled(False)
        self._diagnostics.event("processing:buffer_vector", status="started", summary={"output_path": self._pending_plan.get("output_path", "")})
        self.dock.set_state(ChatState.SENDING, "正在执行已确认的 GIS 缓冲区任务…")
        task = BufferProcessingTask(self._pending_plan, self)
        self._processing_task = task
        task.completed.connect(self._on_processing_completed)
        task.failed.connect(self._on_processing_failed)
        task.cancelled.connect(self._on_processing_cancelled)
        task.start()

    def cancel_pending_plan(self):
        if not self._pending_plan or self._processing_task:
            return
        output_path = self._pending_plan["output_path"]
        self._pending_plan = None
        self.dock.hide_execution_plan()
        self._append("tool", f"已取消执行计划；未生成输出文件：{output_path}")
        self._diagnostics.event("processing:buffer_vector", status="cancelled", summary={"output_path": output_path})
        self.dock.set_state(ChatState.CANCELLED, "执行计划已取消；没有写入或添加图层。")

    def _on_processing_completed(self, result: dict):
        self._pending_plan = None
        self._processing_task = None
        self.dock.hide_execution_plan()
        self._append("tool", f"Processing 成功：已生成 {result['output_path']}，并添加结果图层 {result['output_layer_name']}（{result['feature_count']} 个要素）。")
        self._diagnostics.event("processing:buffer_vector", status="success", summary={"feature_count": result["feature_count"]})
        self.dock.set_state(ChatState.READY, "GIS 处理完成，原始图层未被覆盖。")

    def _on_processing_failed(self, detail: str):
        self._processing_task = None
        self.dock.set_plan_controls_enabled(True)
        self._diagnostics.event("processing:buffer_vector", status="failure", summary=detail)
        self._append("error", f"GIS Processing 失败：{detail}")
        self.dock.set_state(ChatState.ERROR, f"GIS Processing 失败：{detail}")

    def _on_processing_cancelled(self):
        self._processing_task = None
        self._pending_plan = None
        self.dock.hide_execution_plan()
        self._diagnostics.event("processing:buffer_vector", status="cancelled")
        self._append("tool", "GIS Processing 已取消；不会把它显示为成功。")
        self.dock.set_state(ChatState.CANCELLED, "GIS Processing 已取消；请检查是否有残留输出文件。")

    @staticmethod
    def _tool_summary(result: dict) -> str:
        data = result.get("data", {})
        if "layer_count" in data:
            return f"图层数：{data['layer_count']}。"
        if "returned_count" in data:
            return f"返回 {data['returned_count']} 条属性，has_more={data.get('has_more', False)}。"
        if "layer" in data:
            layer = data["layer"]
            return f"图层：{layer.get('name', '')}，CRS：{layer.get('crs', '')}。"
        return "已返回结构化只读结果。"

    def _append(self, role: str, content: str):
        self.dock.append_message(self.view_model.add_message(role, content))

    def _on_failure(self, detail: str):
        if "超时" in detail:
            detail = format_timeout_error(detail, self._active_timeout_seconds)
        self._diagnostics.event("chat_request", status="failure", summary=detail)
        self._append("error", detail)
        self.dock.set_state(ChatState.ERROR, detail)

    def _on_cancelled(self):
        self.dock.set_state(ChatState.CANCELLED, "请求已取消；没有接收模型结果。")
