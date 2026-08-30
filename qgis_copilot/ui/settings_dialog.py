"""Native dialog for non-secret model settings and QGIS-authentication credentials."""

from __future__ import annotations

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
)

from qgis_copilot.models.settings import DEFAULT_TIMEOUT_SECONDS, ModelSettings


class SettingsDialog(QDialog):
    """Collect model settings without ever displaying an already-stored API key."""

    save_requested = pyqtSignal(object, str)
    test_requested = pyqtSignal(object, str)

    def __init__(self, existing: ModelSettings | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("QGIS Copilot 模型设置")
        self.setModal(True)
        self.setMinimumWidth(460)
        self._build_ui(existing)

    def _build_ui(self, existing: ModelSettings | None) -> None:
        layout = QVBoxLayout(self)
        intro = QLabel(
            "API Key 仅写入 QGIS 认证存储，不会保存到普通插件设置或显示在此窗口。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.base_url = QLineEdit(existing.base_url if existing else "")
        self.base_url.setPlaceholderText("https://api.example.com/v1")
        form.addRow("API 地址：", self.base_url)
        self.model_name = QLineEdit(existing.model_name if existing else "")
        self.model_name.setPlaceholderText("例如：gpt-4.1-mini")
        form.addRow("模型名：", self.model_name)
        self.api_key = QLineEdit()
        self.api_key.setObjectName("QgisCopilotApiKeyInput")
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("首次保存必填；留空则保留既有凭据")
        self.api_key_toggle = QToolButton()
        self.api_key_toggle.setObjectName("QgisCopilotApiKeyVisibilityToggle")
        self.api_key_toggle.setText("显示")
        self.api_key_toggle.setCheckable(True)
        self.api_key_toggle.setToolTip("仅显示或隐藏本次手动输入的 API Key；不会读取既有凭据")
        self.api_key_toggle.toggled.connect(self._set_api_key_visibility)
        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.addWidget(self.api_key)
        key_row.addWidget(self.api_key_toggle)
        form.addRow("API Key：", key_row)
        self.timeout = QSpinBox()
        self.timeout.setRange(1, 300)
        self.timeout.setValue(existing.timeout_seconds if existing else DEFAULT_TIMEOUT_SECONDS)
        self.timeout.setSuffix(" 秒")
        form.addRow("超时：", self.timeout)
        layout.addLayout(form)

        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)

        actions = QHBoxLayout()
        self.test_button = QPushButton("测试连通性")
        self.test_button.clicked.connect(self._request_test)
        actions.addWidget(self.test_button)
        actions.addStretch(1)
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self._request_save)
        self.button_box.rejected.connect(self.reject)
        actions.addWidget(self.button_box)
        layout.addLayout(actions)

    def _set_api_key_visibility(self, visible: bool) -> None:
        """Toggle only the text typed into this dialog; stored credentials stay unread."""
        self.api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        self.api_key_toggle.setText("隐藏" if visible else "显示")

    def current_settings(self) -> ModelSettings:
        return ModelSettings(
            base_url=self.base_url.text().strip(),
            model_name=self.model_name.text().strip(),
            timeout_seconds=self.timeout.value(),
        ).validate()

    def set_feedback(self, text: str, is_error: bool = False) -> None:
        self.feedback.setText(text)
        self.feedback.setStyleSheet("color: #a33;" if is_error else "color: palette(mid);")
        self.test_button.setEnabled(True)
        self.button_box.setEnabled(True)

    def set_busy(self, detail: str) -> None:
        self.feedback.setText(detail)
        self.feedback.setStyleSheet("color: palette(mid);")
        self.test_button.setEnabled(False)
        self.button_box.setEnabled(False)

    def _request_save(self) -> None:
        try:
            settings = self.current_settings()
        except ValueError as exc:
            self.set_feedback(str(exc), is_error=True)
            return
        self.save_requested.emit(settings, self.api_key.text())

    def _request_test(self) -> None:
        try:
            settings = self.current_settings()
        except ValueError as exc:
            self.set_feedback(str(exc), is_error=True)
            return
        self.test_requested.emit(settings, self.api_key.text())
