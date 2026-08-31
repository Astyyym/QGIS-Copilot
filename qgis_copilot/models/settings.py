"""Validated, non-secret model settings stored in QGIS user settings."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from qgis.PyQt.QtCore import QSettings

from .capabilities import BehaviorMode, get_profile


SETTINGS_GROUP = "QgisCopilot/model"
DEFAULT_TIMEOUT_SECONDS = 120
MAX_TIMEOUT_SECONDS = 300


class ModelSettingsError(ValueError):
    """Raised when a model configuration cannot safely make a request."""


@dataclass(frozen=True)
class ModelSettings:
    """Non-secret connection and verified capability settings."""

    base_url: str
    model_name: str
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    auth_config_id: str | None = None
    capability_profile_id: str = "standard_openai_compatible"
    behavior_mode: str = BehaviorMode.SERVICE_DEFAULT.value

    def validate(self) -> "ModelSettings":
        parsed = urlparse(self.base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ModelSettingsError("模型地址必须是完整的 http:// 或 https:// URL。")
        if parsed.username or parsed.password:
            raise ModelSettingsError("模型地址不能包含用户名或密码。")
        if not self.model_name.strip():
            raise ModelSettingsError("请填写模型名称。")
        if not 1 <= int(self.timeout_seconds) <= MAX_TIMEOUT_SECONDS:
            raise ModelSettingsError(f"超时必须在 1 到 {MAX_TIMEOUT_SECONDS} 秒之间。")
        profile = get_profile(self.capability_profile_id)
        try:
            mode = BehaviorMode(self.behavior_mode)
        except ValueError as exc:
            raise ModelSettingsError("模型行为模式无效。") from exc
        if not profile.supports(mode):
            raise ModelSettingsError("当前模型能力档案不支持所选行为模式。")
        return self

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"

    @property
    def capability_profile(self):
        return get_profile(self.capability_profile_id)

    @property
    def resolved_behavior_mode(self) -> BehaviorMode:
        return BehaviorMode(self.behavior_mode)


class ModelSettingsStore:
    """Stores endpoint/options only; API secrets stay in QGIS auth storage."""

    def __init__(self, qsettings: QSettings | None = None):
        self._settings = qsettings or QSettings()

    def load(self) -> ModelSettings | None:
        base_url = self._settings.value(f"{SETTINGS_GROUP}/base_url", "", type=str).strip()
        model_name = self._settings.value(f"{SETTINGS_GROUP}/model_name", "", type=str).strip()
        if not base_url and not model_name:
            return None
        timeout = self._settings.value(f"{SETTINGS_GROUP}/timeout_seconds", DEFAULT_TIMEOUT_SECONDS, type=int)
        auth_config_id = self._settings.value(f"{SETTINGS_GROUP}/auth_config_id", "", type=str).strip() or None
        profile_id = self._settings.value(f"{SETTINGS_GROUP}/capability_profile_id", "standard_openai_compatible", type=str)
        mode = self._settings.value(f"{SETTINGS_GROUP}/behavior_mode", BehaviorMode.SERVICE_DEFAULT.value, type=str)
        return ModelSettings(base_url, model_name, timeout, auth_config_id, profile_id, mode).validate()

    def save(self, model_settings: ModelSettings) -> None:
        model_settings.validate()
        self._settings.setValue(f"{SETTINGS_GROUP}/base_url", model_settings.base_url.strip())
        self._settings.setValue(f"{SETTINGS_GROUP}/model_name", model_settings.model_name.strip())
        self._settings.setValue(f"{SETTINGS_GROUP}/timeout_seconds", int(model_settings.timeout_seconds))
        self._settings.setValue(f"{SETTINGS_GROUP}/auth_config_id", model_settings.auth_config_id or "")
        self._settings.setValue(f"{SETTINGS_GROUP}/capability_profile_id", model_settings.capability_profile.profile_id)
        self._settings.setValue(f"{SETTINGS_GROUP}/behavior_mode", model_settings.resolved_behavior_mode.value)

    def clear(self) -> None:
        self._settings.remove(SETTINGS_GROUP)
