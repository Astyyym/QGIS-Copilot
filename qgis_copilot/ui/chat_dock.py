"""Native QGIS dock widget used by the Goal 1 chat workbench."""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .view_models import ChatMessage, ChatState


class ChatDockWidget(QDockWidget):
    """A self-contained native Qt chat surface with explicit UI states."""

    message_submitted = pyqtSignal(str)
    cancel_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    retry_requested = pyqtSignal()
    plan_confirmed = pyqtSignal()
    plan_cancelled = pyqtSignal()

    _STATUS_TEXT = {
        ChatState.EMPTY: "准备就绪：输入一个 GIS 问题开始。",
        ChatState.SENDING: "正在处理请求…",
        ChatState.READY: "准备就绪。",
        ChatState.ERROR: "本次请求未完成。",
        ChatState.CANCELLED: "请求已取消。",
    }

    def __init__(self, parent=None):
        super().__init__("QGIS Copilot", parent)
        self.setObjectName("QgisCopilotChatDock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.setMinimumWidth(320)
        self._message_widgets = []
        self._state = ChatState.EMPTY
        self._build_ui()
        self.set_state(ChatState.EMPTY)

    def _build_ui(self):
        root = QWidget(self)
        root.setObjectName("QgisCopilotChatRoot")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("QGIS Copilot")
        title.setStyleSheet("font-weight: 600; font-size: 15px;")
        header.addWidget(title)
        header.addStretch(1)
        self.settings_button = QToolButton()
        self.settings_button.setText("设置")
        self.settings_button.setToolTip("模型与连接设置（将在 Goal 2 接入）")
        self.settings_button.clicked.connect(self.settings_requested)
        header.addWidget(self.settings_button)
        layout.addLayout(header)

        self.message_container = QWidget()
        self.message_layout = QVBoxLayout(self.message_container)
        self.message_layout.setContentsMargins(0, 0, 0, 0)
        self.message_layout.setSpacing(8)
        self.message_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.message_container)
        layout.addWidget(scroll, 1)
        self.message_scroll = scroll

        self.empty_label = QLabel(
            "你好，我是 QGIS Copilot。\n\n"
            "Goal 1 已搭好聊天工作台；模型、项目读取与 GIS 工具会在后续 Goal 逐步接入。"
        )
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: palette(mid); padding: 24px;")
        self.message_layout.insertWidget(0, self.empty_label)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.status_label)

        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setObjectName("QgisCopilotMessageInput")
        self.input.setPlaceholderText("例如：当前项目有哪些图层？")
        self.input.returnPressed.connect(self._submit_if_valid)
        input_row.addWidget(self.input, 1)

        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("QgisCopilotSendButton")
        self.send_button.clicked.connect(self._submit_if_valid)
        input_row.addWidget(self.send_button)

        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName("QgisCopilotStopButton")
        self.stop_button.clicked.connect(self.cancel_requested)
        input_row.addWidget(self.stop_button)
        layout.addLayout(input_row)

        self.retry_button = QPushButton("重试")
        self.retry_button.setObjectName("QgisCopilotRetryButton")
        self.retry_button.clicked.connect(self.retry_requested)
        layout.addWidget(self.retry_button)

        self.plan_card = QFrame()
        self.plan_card.setObjectName("QgisCopilotExecutionPlan")
        self.plan_card.setFrameShape(QFrame.Shape.StyledPanel)
        plan_layout = QVBoxLayout(self.plan_card)
        self.plan_title = QLabel("待确认执行计划")
        self.plan_title.setStyleSheet("font-weight: 600;")
        self.plan_detail = QLabel()
        self.plan_detail.setWordWrap(True)
        plan_layout.addWidget(self.plan_title)
        plan_layout.addWidget(self.plan_detail)
        plan_actions = QHBoxLayout()
        self.plan_confirm_button = QPushButton("确认执行")
        self.plan_confirm_button.setObjectName("QgisCopilotPlanConfirmButton")
        self.plan_confirm_button.clicked.connect(self.plan_confirmed)
        self.plan_cancel_button = QPushButton("取消计划")
        self.plan_cancel_button.setObjectName("QgisCopilotPlanCancelButton")
        self.plan_cancel_button.clicked.connect(self.plan_cancelled)
        plan_actions.addWidget(self.plan_confirm_button)
        plan_actions.addWidget(self.plan_cancel_button)
        plan_layout.addLayout(plan_actions)
        self.plan_card.hide()
        layout.addWidget(self.plan_card)

        self.setWidget(root)

    def _submit_if_valid(self):
        text = self.input.text().strip()
        if not text or self._state == ChatState.SENDING:
            return
        self.input.clear()
        self.message_submitted.emit(text)

    def append_message(self, message: ChatMessage):
        self.empty_label.hide()
        bubble = QLabel(message.content)
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        if message.role == "user":
            bubble.setStyleSheet(
                "background: palette(highlight); color: palette(highlighted-text); "
                "border-radius: 6px; padding: 8px;"
            )
        elif message.role == "error":
            bubble.setStyleSheet(
                "background: #5a2020; color: white; border-radius: 6px; padding: 8px;"
            )
        else:
            bubble.setStyleSheet(
                "background: palette(base); border: 1px solid palette(midlight); "
                "border-radius: 6px; padding: 8px;"
            )
        self.message_layout.insertWidget(self.message_layout.count() - 1, bubble)
        self._message_widgets.append(bubble)
        self._scroll_to_bottom()

    def clear_messages(self):
        for widget in self._message_widgets:
            self.message_layout.removeWidget(widget)
            widget.deleteLater()
        self._message_widgets.clear()
        self.empty_label.show()

    def set_state(self, state: ChatState, detail: str | None = None):
        self._state = state
        self.status_label.setText(detail or self._STATUS_TEXT[state])
        sending = state == ChatState.SENDING
        errored = state == ChatState.ERROR
        self.input.setEnabled(not sending)
        self.send_button.setEnabled(not sending)
        self.stop_button.setVisible(sending)
        self.stop_button.setEnabled(sending)
        self.retry_button.setVisible(errored or state == ChatState.CANCELLED)

    def show_execution_plan(self, plan: dict):
        inputs = plan["inputs"]
        params = plan["parameters"]
        risks = "\n".join(f"• {risk}" for risk in plan["risks"])
        self.plan_detail.setText(
            f"输入图层：{inputs['layer_name']}（{inputs['feature_count']} 个要素，{inputs['crs']}）\n"
            f"参数：缓冲 {params['distance']} {params.get('distance_unit', '')}，分段 {params['segments']}，融合={params['dissolve']}\n"
            f"输出：{plan['output_path']}（图层：{plan['output_layer_name']}）\n"
            f"影响：{plan['impact']}\n风险：\n{risks}"
        )
        self.plan_card.show()

    def hide_execution_plan(self):
        self.plan_card.hide()

    def set_plan_controls_enabled(self, enabled: bool):
        self.plan_confirm_button.setEnabled(enabled)
        self.plan_cancel_button.setEnabled(enabled)

    def _scroll_to_bottom(self):
        bar = self.message_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
