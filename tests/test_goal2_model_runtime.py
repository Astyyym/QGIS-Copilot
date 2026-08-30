"""Goal 2 executable tests using QGIS's bundled Python and Qt runtime."""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from qgis.PyQt.QtCore import QCoreApplication, QSettings

from qgis_copilot.agent.core import AgentCore
from qgis_copilot.models.base import ChatCompletion
from qgis_copilot.models.openai_compatible import OpenAICompatibleAdapter
from qgis_copilot.models.settings import ModelSettings, ModelSettingsError, ModelSettingsStore
from qgis_copilot.security.credentials import QgisCredentialStore
from qgis_copilot.security.redaction import redact_headers, redact_text
from qgis_copilot.tasks.network import NetworkRequestThread


class _EndpointHandler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.__class__.requests.append((self.path, dict(self.headers), json.loads(body)))
        if self.path == "/v1/chat/completions":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"model": "test-model", "choices": [{"message": {"content": "network ok"}}]}).encode()
            )
        else:
            self.send_error(404)

    def log_message(self, _format, *_args):
        pass


class _FakeAuthManager:
    def __init__(self):
        self.config = None

    def isDisabled(self):
        return False

    def storeAuthenticationConfig(self, config):
        config.setId("auth-test-id")
        self.config = config
        return True

    def updateAuthenticationConfig(self, config):
        if config.id() != "auth-test-id" or not self.config:
            return False
        self.config = config
        return True

    def loadAuthenticationConfig(self, config_id, config, _full):
        if config_id != "auth-test-id" or not self.config:
            return False
        config.setConfig("password", self.config.config("password"))
        return True

    def removeAuthenticationConfig(self, config_id):
        return config_id == "auth-test-id"


class _SlowAdapter:
    def complete(self, _messages, cancel_event):
        for _ in range(80):
            if cancel_event.is_set():
                from qgis_copilot.models.base import ModelCancelledError
                raise ModelCancelledError("cancelled")
            time.sleep(0.01)
        return ChatCompletion("too late")


class GoalTwoModelRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _EndpointHandler)
        cls.server_thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_real_openai_compatible_http_request(self):
        adapter = OpenAICompatibleAdapter(ModelSettings(self.base_url, "test-model", 5), "secret-value")
        completion = adapter.complete([{"role": "user", "content": "ping"}], Event())
        self.assertEqual(completion.content, "network ok")
        path, headers, payload = _EndpointHandler.requests[-1]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer secret-value")
        self.assertEqual(payload["model"], "test-model")

    def test_invalid_settings_and_redaction(self):
        with self.assertRaises(ModelSettingsError):
            ModelSettings("model.local", "x").validate()
        unsafe = "Authorization: Bearer secret-value\napi_key=another-secret"
        safe = redact_text(unsafe)
        self.assertNotIn("secret-value", safe)
        self.assertNotIn("another-secret", safe)
        self.assertEqual(redact_headers({"Authorization": "Bearer secret-value"})["Authorization"], "[REDACTED]")

    def test_qgis_auth_store_seam_and_qsettings_do_not_contain_key(self):
        fake_auth = _FakeAuthManager()
        store = QgisCredentialStore(fake_auth)
        auth_id = store.save_api_key("secret-value")
        self.assertEqual(auth_id, "auth-test-id")
        self.assertEqual(store.load_api_key(auth_id), "secret-value")
        self.assertEqual(store.save_api_key("rotated-secret", auth_id), auth_id)
        self.assertEqual(store.load_api_key(auth_id), "rotated-secret")
        settings_store = ModelSettingsStore(QSettings("QgisCopilotTests", "Goal2"))
        settings_store.clear()
        settings_store.save(ModelSettings(self.base_url, "test-model", 7, auth_id))
        loaded = settings_store.load()
        self.assertEqual(loaded.auth_config_id, auth_id)
        self.assertNotIn("secret-value", str(settings_store._settings.allKeys()))
        settings_store.clear()

    def test_agent_budget_is_bounded(self):
        agent = AgentCore("system", max_steps=1)
        request_messages = agent.begin("hello")
        self.assertEqual(request_messages[-1]["content"], "hello")
        with self.assertRaises(RuntimeError):
            agent.begin("again")

    def test_network_thread_cancels_without_completion(self):
        thread = NetworkRequestThread(_SlowAdapter(), [{"role": "user", "content": "wait"}])
        events = []
        thread.completed.connect(lambda _completion: events.append("completed"))
        thread.cancelled.connect(lambda: events.append("cancelled"))
        thread.start()
        time.sleep(0.05)
        thread.cancel()
        deadline = time.monotonic() + 3
        while thread.isRunning() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        self.assertFalse(thread.isRunning())
        self.assertEqual(events, ["cancelled"])


if __name__ == "__main__":
    unittest.main()
