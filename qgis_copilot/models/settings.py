"""Validated, non-secret model settings stored in QGIS user settings."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from qgis.PyQt.QtCore import QSettings


SETTINGS_GROUP = "QgisCopilot/model"
DEFAULT_TIMEOUT_SECONDS = 120
MAX_TIMEOUT_SECONDS = 300


class ModelSettingsError(ValueError):
    """Raised when a model configuration cannot safely make a request."""


@dataclass(frozen=True)
class ModelSettings:
    """Non-secret connection settings for an OpenAI-compatible endpoint."""

    base_url: str
    model_name: str
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    auth_config_id: str | None = None

    def validate(self) -> "ModelSettings":
        parsed = urlparse(self.base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ModelSettingsError("模型地址必须是完整的 http:// 或 https:// URL。")
        if parsed.username or parsed.password:
            raise ModelSettingsError("模型地址不能包含用户名或密码。")
        if not self.model_name.strip():
            raise ModelSettingsError("请填写模型名称。")
        if not 1 <= int(self.timeout_seconds) <= MAX_TIMEOUT_SECONDS:
            raise ModelSettingsError(
                f"超时必须在 1 到 {MAX_TIMEOUT_SECONDS} 秒之间。"
            )
        return self

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"


class ModelSettingsStore:
    """Stores only endpoint, model and timeout; API secrets stay in auth storage."""

    def __init__(self, qsettings: QSettings | None = None):
        self._settings = qsettings or QSettings()

    def load(self) -> ModelSettings | None:
        base_url = self._settings.value(f"{SETTINGS_GROUP}/base_url", "", type=str).strip()
        model_name = self._settings.value(f"{SETTINGS_GROUP}/model_name", "", type=str).strip()
        if not base_url and not model_name:
            return None
        timeout = self._settings.value(
            f"{SETTINGS_GROUP}/timeout_seconds", DEFAULT_TIMEOUT_SECONDS, type=int
        )
        auth_config_id = self._settings.value(
            f"{SETTINGS_GROUP}/auth_config_id", "", type=str
        ).strip() or None
        return ModelSettings(base_url, model_name, timeout, auth_config_id).validate()

    def save(self, model_settings: ModelSettings) -> None:
        model_settings.validate()
        self._settings.setValue(f"{SETTINGS_GROUP}/base_url", model_settings.base_url.strip())
        self._settings.setValue(f"{SETTINGS_GROUP}/model_name", model_settings.model_name.strip())
        self._settings.setValue(
            f"{SETTINGS_GROUP}/timeout_seconds", int(model_settings.timeout_seconds)
        )
        self._settings.setValue(
            f"{SETTINGS_GROUP}/auth_config_id", model_settings.auth_config_id or ""
        )

    def clear(self) -> None:
        self._settings.remove(SETTINGS_GROUP)
