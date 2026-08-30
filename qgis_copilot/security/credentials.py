"""QGIS authentication-manager storage for API credentials."""

from __future__ import annotations

from qgis.core import QgsApplication, QgsAuthMethodConfig

AUTH_METHOD = "Basic"
AUTH_DESCRIPTION = "QGIS Copilot OpenAI-compatible API key"


class CredentialStoreError(RuntimeError):
    """QGIS authentication storage was unavailable or refused the request."""


class QgisCredentialStore:
    """Persists an API key only in QGIS's encrypted authentication database."""

    def __init__(self, auth_manager=None):
        self._auth_manager = auth_manager if auth_manager is not None else QgsApplication.authManager()

    def save_api_key(self, api_key: str, auth_config_id: str | None = None) -> str:
        if not api_key or not api_key.strip():
            raise CredentialStoreError("API Key 不能为空。")
        if self._auth_manager.isDisabled():
            raise CredentialStoreError("QGIS 认证存储不可用；请先解锁或配置认证主密码。")

        config = QgsAuthMethodConfig()
        config.setName(AUTH_DESCRIPTION)
        config.setMethod(AUTH_METHOD)
        config.setConfig("username", "api_key")
        config.setConfig("password", api_key.strip())

        # QGIS rejects storeAuthenticationConfig() with an existing ID. Updating an
        # existing credential must use its dedicated API instead of re-storing it.
        if auth_config_id:
            config.setId(auth_config_id)
            if not self._auth_manager.updateAuthenticationConfig(config):
                raise CredentialStoreError("QGIS 未能更新已保存的 API Key。")
            return auth_config_id

        result = self._auth_manager.storeAuthenticationConfig(config)
        # QGIS 4's Python binding returns (success, config); earlier bindings may
        # return only a bool. Handle both without relying on truthiness of a tuple.
        if isinstance(result, tuple):
            stored, stored_config = result
            if stored and stored_config:
                config = stored_config
        else:
            stored = result
        if not stored:
            raise CredentialStoreError("QGIS 未能保存 API Key 到认证存储。")
        return config.id()

    def load_api_key(self, auth_config_id: str | None) -> str:
        if not auth_config_id:
            raise CredentialStoreError("尚未保存 API Key。")
        if self._auth_manager.isDisabled():
            raise CredentialStoreError("QGIS 认证存储不可用；请先解锁或配置认证主密码。")
        config = QgsAuthMethodConfig()
        if not self._auth_manager.loadAuthenticationConfig(auth_config_id, config, True):
            raise CredentialStoreError("无法从 QGIS 认证存储读取 API Key。")
        api_key = config.config("password", "")
        if not api_key:
            raise CredentialStoreError("认证存储中没有可用的 API Key。")
        return api_key

    def remove(self, auth_config_id: str | None) -> bool:
        return bool(auth_config_id and self._auth_manager.removeAuthenticationConfig(auth_config_id))
