"""Native transparent QGIS Copilot workbench dock."""
from __future__ import annotations

import json

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDockWidget, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from .view_models import ChatMessage, ChatState, ToolCard, WorkbenchStage


class ChatDockWidget(QDockWidget):
    """Native workbench that displays real state, bounded traces and safe actions."""

    message_submitted = pyqtSignal(str)
    cancel_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    retry_requested = pyqtSignal()
    plan_confirmed = pyqtSignal()
    plan_cancelled = pyqtSignal()
    layer_zoom_requested = pyqtSignal(str)
    layer_attributes_requested = pyqtSignal(str)
    output_path_requested = pyqtSignal(str)
    new_session_requested = pyqtSignal()
    session_selected = pyqtSignal(int)

    _STAGE_TEXT = {
        WorkbenchStage.READY: "准备就绪。",
        WorkbenchStage.MODEL_ANALYSIS: "模型分析中…",
        WorkbenchStage.READING_PROJECT: "正在读取项目…",
        WorkbenchStage.CALLING_TOOL: "正在调用工具…",
        WorkbenchStage.WAITING_CONFIRMATION: "等待确认：尚未写入。",
        WorkbenchStage.PROCESSING: "QGIS Processing 正在执行…",
        WorkbenchStage.COMPLETED: "本轮完成。",
        WorkbenchStage.FAILED: "本轮未完成。",
        WorkbenchStage.CANCELLED: "本轮已取消。",
    }

    def __init__(self, parent=None):
        super().__init__("QGIS Copilot", parent)
        self.setObjectName("QgisCopilotChatDock")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setMinimumWidth(350)
        self._message_widgets = []
        self._card_widgets = []
        self._state = ChatState.EMPTY
        self._build_ui()
        self.set_stage(WorkbenchStage.READY)

    def _build_ui(self):
        root = QWidget(self); root.setObjectName("QgisCopilotChatRoot")
        layout = QVBoxLayout(root); layout.setContentsMargins(12, 12, 12, 12); layout.setSpacing(8)
        header = QHBoxLayout(); title = QLabel("QGIS Copilot")
        title.setStyleSheet("font-weight: 600; font-size: 15px;"); header.addWidget(title); header.addStretch(1)
        self.settings_button = QToolButton(); self.settings_button.setText("设置")
        self.settings_button.setToolTip("模型连接、能力档案与行为模式")
        self.settings_button.clicked.connect(self.settings_requested); header.addWidget(self.settings_button); layout.addLayout(header)
        self.new_session_button = QToolButton(); self.new_session_button.setText("新建会话")
        self.new_session_button.setToolTip("清空当前聊天与审计记录，不修改 QGIS 项目")
        self.new_session_button.clicked.connect(self.new_session_requested); header.insertWidget(1, self.new_session_button)
        self.session_selector = QComboBox(); self.session_selector.setObjectName("QgisCopilotSessionSelector")
        self.session_selector.setToolTip("切换本次 QGIS 运行期间保留的会话")
        self.session_selector.currentIndexChanged.connect(self.session_selected)
        header.insertWidget(2, self.session_selector)
        self.session_info = QLabel(); self.session_info.setObjectName("QgisCopilotSessionInfo")
        self.session_info.setWordWrap(True); self.session_info.setStyleSheet("background: palette(alternate-base); border-radius: 5px; padding: 7px;")
        layout.addWidget(self.session_info)
        self.message_container = QWidget(); self.message_layout = QVBoxLayout(self.message_container)
        self.message_layout.setContentsMargins(0, 0, 0, 0); self.message_layout.setSpacing(8); self.message_layout.addStretch(1)
        self.empty_label = QLabel("我是 QGIS Copilot。可以读取当前项目与图层信息；涉及新输出图层时，我会先生成计划，等待你确认后才执行。")
        self.empty_label.setWordWrap(True); self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: palette(mid); padding: 20px;"); self.message_layout.insertWidget(0, self.empty_label)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame); scroll.setWidget(self.message_container)
        layout.addWidget(scroll, 1); self.message_scroll = scroll
        self.quick_tasks = QFrame(); quick_layout = QVBoxLayout(self.quick_tasks); quick_layout.setContentsMargins(6, 6, 6, 6)
        quick_layout.addWidget(QLabel("快捷任务（只填入，可编辑）：")); buttons = QHBoxLayout()
        for label, prompt in (("项目诊断", "检查当前项目的健康状态。"), ("图层/CRS", "查看当前项目的图层与坐标系。"), ("字段统计", "分析指定图层的字段数据。"), ("表达式筛选", "帮我预览一个表达式筛选条件。"), ("空间关系", "帮我分析两个图层的空间关系。"), ("处理/导出", "帮我规划安全的数据处理或导出。")):
            button = QToolButton(); button.setText(label); button.setToolTip(prompt); button.clicked.connect(lambda _checked=False, text=prompt: self.input.setText(text)); buttons.addWidget(button)
        quick_layout.addLayout(buttons); layout.addWidget(self.quick_tasks)
        self.status_label = QLabel(); self.status_label.setWordWrap(True); self.status_label.setStyleSheet("color: palette(mid);"); layout.addWidget(self.status_label)
        input_row = QHBoxLayout(); self.input = QLineEdit(); self.input.setObjectName("QgisCopilotMessageInput")
        self.input.setPlaceholderText("例如：当前项目有哪些图层？"); self.input.returnPressed.connect(self._submit_if_valid); input_row.addWidget(self.input, 1)
        self.send_button = QPushButton("发送"); self.send_button.setObjectName("QgisCopilotSendButton"); self.send_button.clicked.connect(self._submit_if_valid); input_row.addWidget(self.send_button)
        self.stop_button = QPushButton("停止"); self.stop_button.setObjectName("QgisCopilotStopButton"); self.stop_button.clicked.connect(self.cancel_requested); input_row.addWidget(self.stop_button); layout.addLayout(input_row)
        self.retry_button = QPushButton("重试"); self.retry_button.clicked.connect(self.retry_requested); layout.addWidget(self.retry_button)
        self.plan_card = QFrame(); self.plan_card.setObjectName("QgisCopilotExecutionPlan"); self.plan_card.setFrameShape(QFrame.Shape.StyledPanel)
        plan_layout = QVBoxLayout(self.plan_card); self.plan_title = QLabel("待确认执行计划"); self.plan_title.setStyleSheet("font-weight: 600;"); self.plan_detail = QLabel(); self.plan_detail.setWordWrap(True)
        plan_layout.addWidget(self.plan_title); plan_layout.addWidget(self.plan_detail); plan_actions = QHBoxLayout()
        self.plan_confirm_button = QPushButton("确认执行"); self.plan_confirm_button.clicked.connect(self.plan_confirmed)
        self.plan_cancel_button = QPushButton("取消计划"); self.plan_cancel_button.clicked.connect(self.plan_cancelled)
        plan_actions.addWidget(self.plan_confirm_button); plan_actions.addWidget(self.plan_cancel_button); plan_layout.addLayout(plan_actions); self.plan_card.hide(); layout.addWidget(self.plan_card)
        self.audit_card = QFrame(); audit_layout = QVBoxLayout(self.audit_card); audit_layout.setContentsMargins(6, 6, 6, 6)
        audit_title = QLabel("本轮审计记录"); audit_title.setStyleSheet("font-weight: 600;"); audit_layout.addWidget(audit_title)
        self.audit_detail = QLabel("尚无活动会话。"); self.audit_detail.setObjectName("QgisCopilotAuditRecord"); self.audit_detail.setWordWrap(True); audit_layout.addWidget(self.audit_detail); layout.addWidget(self.audit_card)
        self.setWidget(root)

    def update_session_info(self, info: dict):
        self.session_info.setText("项目：{project_name}（{saved_state}，{layer_count} 个图层）\n模型：{model_name}｜{interface_type}｜{connection_state}\n行为：{behavior_mode}｜执行：{execution_mode}".format(**info))

    def set_stage(self, stage: WorkbenchStage, detail: str | None = None):
        self.status_label.setText(detail or self._STAGE_TEXT[stage])
        sending = stage in {WorkbenchStage.MODEL_ANALYSIS, WorkbenchStage.READING_PROJECT, WorkbenchStage.CALLING_TOOL, WorkbenchStage.PROCESSING}
        self._state = ChatState.SENDING if sending else (ChatState.ERROR if stage == WorkbenchStage.FAILED else ChatState.CANCELLED if stage == WorkbenchStage.CANCELLED else ChatState.READY)
        self.input.setEnabled(not sending); self.send_button.setEnabled(not sending); self.stop_button.setVisible(sending); self.stop_button.setEnabled(sending)
        self.retry_button.setVisible(stage in {WorkbenchStage.FAILED, WorkbenchStage.CANCELLED})

    def set_state(self, state: ChatState, detail: str | None = None):
        mapping = {ChatState.EMPTY: WorkbenchStage.READY, ChatState.SENDING: WorkbenchStage.MODEL_ANALYSIS, ChatState.READY: WorkbenchStage.READY, ChatState.ERROR: WorkbenchStage.FAILED, ChatState.CANCELLED: WorkbenchStage.CANCELLED}
        self.set_stage(mapping[state], detail)

    def _submit_if_valid(self):
        text = self.input.text().strip()
        if text and self._state != ChatState.SENDING: self.input.clear(); self.message_submitted.emit(text)

    def append_message(self, message: ChatMessage):
        self.empty_label.hide(); bubble = QLabel(message.content); bubble.setWordWrap(True); bubble.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        styles = {"user": "background: palette(highlight); color: palette(highlighted-text);", "error": "background: #5a2020; color: white;"}
        bubble.setStyleSheet(styles.get(message.role, "background: palette(base); border: 1px solid palette(midlight);") + " border-radius: 6px; padding: 8px;")
        self.message_layout.insertWidget(self.message_layout.count() - 1, bubble); self._message_widgets.append(bubble); self._scroll_to_bottom()

    def clear_session_view(self):
        """Remove visible chat cards/messages without touching the QGIS project."""
        for widget in self._message_widgets + self._card_widgets:
            widget.deleteLater()
        self._message_widgets.clear(); self._card_widgets.clear()
        self.empty_label.show()
        self.input.clear()
        self.audit_detail.setText("尚无活动会话。")
        self.hide_execution_plan()

    def set_session_items(self, labels: list[str], current: int):
        self.session_selector.blockSignals(True)
        self.session_selector.clear(); self.session_selector.addItems(labels)
        if labels: self.session_selector.setCurrentIndex(current)
        self.session_selector.blockSignals(False)

    def add_tool_card(self, card: ToolCard):
        frame = QFrame(); frame.setFrameShape(QFrame.Shape.StyledPanel); box = QVBoxLayout(frame); title = QLabel(card.title); title.setStyleSheet("font-weight: 600;")
        summary = QLabel(card.summary); summary.setWordWrap(True); detail = QLabel(card.detail); detail.setObjectName("QgisCopilotToolCardDetail"); detail.setWordWrap(True); detail.hide()
        toggle = QToolButton(); toggle.setText("查看详情"); toggle.setCheckable(True); toggle.toggled.connect(lambda shown: (detail.setVisible(shown), toggle.setText("收起详情" if shown else "查看详情")))
        box.addWidget(title); box.addWidget(summary); box.addWidget(toggle); box.addWidget(detail)
        if card.actions:
            actions = QHBoxLayout()
            for action in card.actions:
                button = QPushButton(action.label)
                button.setObjectName(f"QgisCopilotResultAction_{action.kind}")
                button.clicked.connect(lambda _checked=False, selected=action: self._emit_result_action(selected.kind, selected.target))
                actions.addWidget(button)
            actions.addStretch(1)
            box.addLayout(actions)
        self.message_layout.insertWidget(self.message_layout.count() - 1, frame); self._card_widgets.append(frame); self._scroll_to_bottom()

    def restore_session_view(self, messages, cards, audit_lines, plan=None):
        self.clear_session_view()
        for message in messages:
            self.append_message(message)
        for card in cards:
            self.add_tool_card(card)
        self.set_audit_record(audit_lines)
        if plan:
            self.show_execution_plan(plan)
            self.set_plan_controls_enabled(True)

    def _emit_result_action(self, kind: str, target: str):
        if kind == "zoom_layer":
            self.layer_zoom_requested.emit(target)
        elif kind == "open_attributes":
            self.layer_attributes_requested.emit(target)
        elif kind == "open_output_path":
            self.output_path_requested.emit(target)

    def set_audit_record(self, lines: list[str]): self.audit_detail.setText("\n".join(lines) if lines else "尚无活动会话。")

    def show_execution_plan(self, plan: dict):
        risks = "\n".join(f"• {risk}" for risk in plan.get("risks", []))
        inputs = plan.get("inputs", {})
        if "input_layer_name" in inputs or "overlay_layer_name" in inputs:
            input_text = (
                f"输入：{inputs.get('input_layer_name', '未指定')}（{inputs.get('input_feature_count', '?')} 个要素）\n"
                f"叠加：{inputs.get('overlay_layer_name', '未指定')}（{inputs.get('overlay_feature_count', '?')} 个要素）"
            )
        else:
            input_text = f"输入：{inputs.get('layer_name', '未指定')}（{inputs.get('feature_count', '?')} 个要素）"
        self.plan_detail.setText(f"{input_text}\n参数：{json.dumps(plan.get('parameters', {}), ensure_ascii=False, default=str)}\n输出：{plan.get('output_path', '未指定')}\n影响：{plan.get('impact', '')}\n风险：\n{risks}")
        self.plan_card.show()

    def hide_execution_plan(self): self.plan_card.hide()
    def set_plan_controls_enabled(self, enabled: bool): self.plan_confirm_button.setEnabled(enabled); self.plan_cancel_button.setEnabled(enabled)
    def _scroll_to_bottom(self): bar = self.message_scroll.verticalScrollBar(); bar.setValue(bar.maximum())
