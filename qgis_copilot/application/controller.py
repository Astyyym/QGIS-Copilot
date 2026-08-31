"""Connect chat UI, settings, bounded Agent and background model requests."""

from __future__ import annotations

import json
from pathlib import Path

from qgis.PyQt.QtCore import QObject
from qgis.core import QgsProject
from qgis.utils import iface as qgis_iface

from qgis_copilot.agent.core import AgentCore
from qgis_copilot.context.project_context import build_model_project_context
from qgis_copilot.diagnostics.logging import DiagnosticsLogger
from qgis_copilot.models.base import ChatCompletion
from qgis_copilot.models.openai_compatible import OpenAICompatibleAdapter
from qgis_copilot.models.settings import ModelSettings, ModelSettingsStore
from qgis_copilot.security.credentials import CredentialStoreError, QgisCredentialStore
from qgis_copilot.security.redaction import redact_text
from qgis_copilot.tasks.network import NetworkRequestThread
from qgis_copilot.tasks.processing import BufferProcessingTask, RasterOrganizationProcessingTask, RasterSlopeProcessingTask, ReprojectProcessingTask, VectorProcessingTask
from qgis_copilot.tools.contracts import PermissionLevel
from qgis_copilot.tools.qgis_tools import create_default_registry
from qgis_copilot.ui.chat_dock import ChatDockWidget
from qgis_copilot.ui.settings_dialog import SettingsDialog
from qgis_copilot.ui.view_models import ChatState, ChatViewModel, ToolCard, WorkbenchStage

_SYSTEM_PROMPT = "你是 QGIS Copilot。只读工具可直接调用。对于缓冲、重投影、裁剪、筛选导出、相交、融合、DEM 坡度、栅格裁剪、栅格重投影或分区统计请求，只能调用对应工具生成计划；计划会在界面展示，必须等待用户点击确认后才会执行 Processing。不得请求或声称执行写入、删除、覆盖、保存项目或任意代码。工具返回后必须根据真实结果回答，不能编造。"


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
        self._audit_lines = []
        self._sessions = [{"agent": self._agent, "view_model": self.view_model, "audit": [], "plan": None}]
        self._current_session_index = 0
        self.dock.message_submitted.connect(self.submit_message)
        self.dock.cancel_requested.connect(self.cancel_request)
        self.dock.retry_requested.connect(self.retry_last_message)
        self.dock.plan_confirmed.connect(self.confirm_pending_plan)
        self.dock.plan_cancelled.connect(self.cancel_pending_plan)
        self.dock.settings_requested.connect(self.show_settings)
        self.dock.layer_zoom_requested.connect(self.zoom_to_layer)
        self.dock.layer_attributes_requested.connect(self.open_attribute_table)
        self.dock.output_path_requested.connect(self.open_output_path)
        self.dock.new_session_requested.connect(self.new_session)
        self.dock.session_selected.connect(self.switch_session)
        self._refresh_session_selector()

    def _save_current_session(self):
        self._sessions[self._current_session_index] = {"agent": self._agent, "view_model": self.view_model, "audit": list(self._audit_lines), "plan": self._pending_plan}

    def _refresh_session_selector(self):
        self.dock.set_session_items([f"会话 {i + 1}" for i in range(len(self._sessions))], self._current_session_index)

    def switch_session(self, index: int):
        if index < 0 or index >= len(self._sessions) or index == self._current_session_index:
            return
        if self._network_thread or self._processing_task:
            self._refresh_session_selector()
            self.dock.set_stage(WorkbenchStage.FAILED, "当前请求或 Processing 正在运行，请完成或停止后再切换会话。")
            return
        self._save_current_session()
        self._current_session_index = index
        saved = self._sessions[index]
        self._agent, self.view_model = saved["agent"], saved["view_model"]
        self._audit_lines, self._pending_plan = list(saved["audit"]), saved["plan"]
        self.dock.restore_session_view(self.view_model.messages, self.view_model.cards, self._audit_lines, self._pending_plan)
        self._refresh_session_selector()
        self.dock.set_stage(WorkbenchStage.WAITING_CONFIRMATION if self._pending_plan else WorkbenchStage.READY, "已切换到历史会话。")

    def new_session(self):
        """Clear chat state only when no network/Processing operation is active."""
        if self._network_thread or self._processing_task:
            self.dock.set_stage(WorkbenchStage.FAILED, "当前请求或 Processing 正在运行，请先停止后再新建会话。")
            return
        self._save_current_session()
        self._agent = AgentCore(_SYSTEM_PROMPT, max_steps=3, tool_registry=self.tool_registry)
        self.view_model = ChatViewModel()
        self._last_message = None
        self._pending_plan = None
        self._audit_lines = []
        self._sessions.append({"agent": self._agent, "view_model": self.view_model, "audit": [], "plan": None})
        self._current_session_index = len(self._sessions) - 1
        self.dock.clear_session_view()
        self._refresh_session_selector()
        self.dock.set_stage(WorkbenchStage.READY, "已新建会话；未修改 QGIS 项目或图层。")

    def zoom_to_layer(self, layer_id: str):
        """Zoom the real map canvas to a current layer; never alters project data."""
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer is None or not layer.isValid():
            self._result_action_error("缩放至图层", "目标图层已不存在或不可用。")
            return
        iface = qgis_iface
        if iface is None or iface.mapCanvas() is None:
            self._result_action_error("缩放至图层", "当前 QGIS 地图画布不可用。")
            return
        canvas = iface.mapCanvas()
        canvas.setExtent(layer.extent())
        canvas.refresh()
        self._audit(f"结果动作：已缩放至图层 {layer.name()}；未修改项目或数据")
        self.dock.set_stage(WorkbenchStage.COMPLETED, f"已缩放至图层：{layer.name()}。")

    def open_attribute_table(self, layer_id: str):
        """Open the native QGIS attribute table only for a current vector layer."""
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer is None or not layer.isValid():
            self._result_action_error("打开属性表", "目标图层已不存在或不可用。")
            return
        if not hasattr(layer, "fields") or not hasattr(layer, "getFeatures"):
            self._result_action_error("打开属性表", "目标图层不支持属性表。")
            return
        iface = qgis_iface
        if iface is None:
            self._result_action_error("打开属性表", "当前 QGIS 界面不可用。")
            return
        iface.showAttributeTable(layer)
        self._audit(f"结果动作：已打开属性表 {layer.name()}；未修改项目或数据")
        self.dock.set_stage(WorkbenchStage.COMPLETED, f"已打开属性表：{layer.name()}。")

    def open_output_path(self, raw_path: str):
        """Open an existing output's containing folder, never create or overwrite files."""
        path = Path(raw_path)
        target = path if path.is_dir() else path.parent
        if not path.exists() or not target.is_dir():
            self._result_action_error("查看输出路径", "输出文件或目录已不存在。")
            return
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtGui import QDesktopServices
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
            self._result_action_error("查看输出路径", "QGIS 无法打开输出目录。")
            return
        self._audit(f"结果动作：已查看输出目录 {target}；未修改项目或数据")
        self.dock.set_stage(WorkbenchStage.COMPLETED, "已打开输出目录。")

    def _result_action_error(self, action: str, detail: str):
        self._audit(f"结果动作不可用：{action}；{detail}")
        self.dock.set_stage(WorkbenchStage.FAILED, f"{action}失败：{detail}")

    @staticmethod
    def _result_actions(result: dict):
        """Expose only actions backed by result IDs/paths; stale targets revalidate on click."""
        from qgis_copilot.ui.view_models import ResultAction
        data = result.get("data", {})
        layer = data.get("layer", {}) if isinstance(data.get("layer"), dict) else {}
        layer_id = data.get("layer_id") or layer.get("id")
        actions = []
        if isinstance(layer_id, str) and layer_id:
            actions.extend((
                ResultAction("zoom_layer", "缩放至图层", layer_id),
                ResultAction("open_attributes", "打开属性表", layer_id),
            ))
        output_path = data.get("output_path")
        if isinstance(output_path, str) and output_path:
            actions.append(ResultAction("open_output_path", "查看输出路径", output_path))
        return tuple(actions)

    def activate(self):
        self._active = True
        self._refresh_session_info()
        self.dock.set_stage(WorkbenchStage.READY)

    def _refresh_session_info(self):
        project = QgsProject.instance()
        try:
            settings = self._settings_store.load()
        except ValueError:
            settings = None
        self.dock.update_session_info({
            "project_name": project.title() or "未命名项目",
            "saved_state": "已保存" if project.fileName() else "未保存",
            "layer_count": len(project.mapLayers()),
            "model_name": settings.model_name if settings else "未配置",
            "interface_type": settings.capability_profile.interface_type if settings else "未连接",
            "connection_state": "已配置" if settings else "未配置",
            "behavior_mode": (settings.behavior_mode if settings else "服务默认").replace("service_default", "服务默认"),
            "execution_mode": "只读；写入需确认",
        })

    def _audit(self, detail: str):
        self._audit_lines.append(detail)
        self.dock.set_audit_record(self._audit_lines[-12:])

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
        self._audit_lines = [f"模型：{settings.model_name}；行为：{settings.behavior_mode}", f"用户请求：{text}"]
        self._refresh_session_info()
        self._audit("执行边界：只读工具可直接读取；写入计划必须确认")
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
        self.dock.set_stage(WorkbenchStage.MODEL_ANALYSIS, "正在生成回答…")
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
            self._audit("完成：模型返回自然语言结论")
            self.dock.set_stage(WorkbenchStage.COMPLETED)
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
        self._audit(f"调用工具：{tool_call.name}")
        self.dock.set_stage(WorkbenchStage.CALLING_TOOL, f"正在准备工具：{tool_call.name}…")
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
            self._audit(f"工具失败：{tool_call.name}；{detail}")
            self.dock.set_stage(WorkbenchStage.FAILED, f"工具调用失败：{detail}")
            return
        if spec.permission == PermissionLevel.WRITE:
            # The provider has already returned an assistant tool_call. Persist a
            # matching *plan-only* tool result before pausing for UI confirmation;
            # otherwise a later user message replays an orphaned function call and
            # strict OpenAI-compatible providers correctly reject it with HTTP 400.
            self._agent.accept_tool_result(tool_call, result)
            self._pending_plan = result.data
            self.dock.show_execution_plan(result.data)
            self.dock.set_plan_controls_enabled(True)
            self._audit(f"待确认写入：{result.data['title']}；尚未创建文件")
            self.dock.set_stage(WorkbenchStage.WAITING_CONFIRMATION, "已生成执行计划；请核对影响与输出路径后确认或取消。")
            self._append("tool", f"已生成待确认计划：{result.data['title']}。尚未创建文件或添加图层。")
            return
        self._agent.accept_tool_result(tool_call, result)
        summary = self._tool_summary(result.as_dict())
        self._append("tool", f"工具完成：{tool_call.name}。{summary}")
        self.dock.add_tool_card(ToolCard(
            tool_call.name,
            summary,
            json.dumps(result.as_dict(), ensure_ascii=False, default=str),
            actions=self._result_actions(result.as_dict()),
        ))
        self.view_model.cards.append(ToolCard(
            tool_call.name, summary,
            json.dumps(result.as_dict(), ensure_ascii=False, default=str),
            actions=self._result_actions(result.as_dict()),
        ))
        self._audit(f"工具完成：{tool_call.name}；{summary}")
        self.dock.set_stage(WorkbenchStage.MODEL_ANALYSIS, f"工具完成：{tool_call.name}。正在继续…")

    def confirm_pending_plan(self):
        if not self._pending_plan or self._processing_task:
            return
        self.dock.set_plan_controls_enabled(False)
        tool_name = self._pending_plan.get("tool", "buffer_vector")
        self._diagnostics.event(f"processing:{tool_name}", status="started", summary={"output_path": self._pending_plan.get("output_path", "")})
        self._audit("用户确认：开始 QGIS Processing")
        self.dock.set_stage(WorkbenchStage.PROCESSING, f"正在执行已确认的 {tool_name} 任务…")
        task_type = {"reproject_layer": ReprojectProcessingTask, "slope_from_dem": RasterSlopeProcessingTask, "clip_raster_by_mask": RasterOrganizationProcessingTask, "reproject_raster": RasterOrganizationProcessingTask, "zonal_statistics": RasterOrganizationProcessingTask, "clip_vector": VectorProcessingTask, "export_filtered_features": VectorProcessingTask, "intersection": VectorProcessingTask, "dissolve": VectorProcessingTask}.get(tool_name, BufferProcessingTask)
        task = task_type(self._pending_plan, self)
        self._processing_task = task
        task.completed.connect(self._on_processing_completed)
        task.failed.connect(self._on_processing_failed)
        task.cancelled.connect(self._on_processing_cancelled)
        task.start()

    def cancel_pending_plan(self):
        if not self._pending_plan or self._processing_task:
            return
        tool_name = self._pending_plan.get("tool", "buffer_vector")
        output_path = self._pending_plan["output_path"]
        self._pending_plan = None
        self.dock.hide_execution_plan()
        self._append("tool", f"已取消执行计划；未生成输出文件：{output_path}")
        self._diagnostics.event(f"processing:{tool_name}", status="cancelled", summary={"output_path": output_path})
        self.dock.set_state(ChatState.CANCELLED, "执行计划已取消；没有写入或添加图层。")

    def _on_processing_completed(self, result: dict):
        self._pending_plan = None
        self._processing_task = None
        self.dock.hide_execution_plan()
        output_count = result.get("feature_count")
        output_summary = f"{output_count} 个要素" if output_count is not None else "栅格结果"
        self._append("tool", f"Processing 成功：已生成 {result['output_path']}，并添加结果图层 {result['output_layer_name']}（{output_summary}）。")
        self._diagnostics.event(f"processing:{result.get('tool', 'reproject_layer' if 'target_crs' in result else 'buffer_vector')}", status="success", summary={"feature_count": output_count if output_count is not None else 0})
        self.dock.add_tool_card(ToolCard(
            "Processing 输出",
            f"已生成 {result['output_layer_name']}（{output_summary}）。",
            json.dumps(result, ensure_ascii=False, default=str),
            actions=self._result_actions(result),
        ))
        self.view_model.cards.append(ToolCard(
            "Processing 输出",
            f"已生成 {result['output_layer_name']}（{output_summary}）。",
            json.dumps(result, ensure_ascii=False, default=str),
            actions=self._result_actions(result),
        ))
        self._audit(f"完成：输出 {result['output_layer_name']}；{output_summary}；源图层未覆盖")
        self._refresh_session_info()
        self.dock.set_stage(WorkbenchStage.COMPLETED, "GIS 处理完成，原始图层未被覆盖。")

    def _on_processing_failed(self, detail: str):
        self._processing_task = None
        self.dock.set_plan_controls_enabled(True)
        self._diagnostics.event("processing:write", status="failure", summary=detail)
        self._append("error", f"GIS Processing 失败：{detail}")
        self._audit(f"Processing 失败：{detail}")
        self.dock.set_stage(WorkbenchStage.FAILED, f"GIS Processing 失败：{detail}")

    def _on_processing_cancelled(self):
        self._processing_task = None
        self._pending_plan = None
        self.dock.hide_execution_plan()
        self._diagnostics.event("processing:write", status="cancelled")
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
