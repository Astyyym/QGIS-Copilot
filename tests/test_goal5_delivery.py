"""Goal 5 security, diagnostics and repeatable packaging regression tests."""
from __future__ import annotations

import io
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from qgis.PyQt.QtWidgets import QApplication, QLineEdit

from package_plugin import build_plugin_zip, validate_plugin_zip
from qgis_copilot.diagnostics.logging import DiagnosticsLogger
from qgis_copilot.models.settings import ModelSettings
from qgis_copilot.security.redaction import redact_text
from qgis_copilot.ui.settings_dialog import SettingsDialog


class GoalFiveSecurityAndDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_api_key_visibility_only_toggles_current_input(self):
        dialog = SettingsDialog(ModelSettings("https://example.test/v1", "demo", 120, "saved-auth-id"))
        self.assertEqual(dialog.api_key.text(), "")
        self.assertEqual(dialog.api_key.echoMode(), QLineEdit.EchoMode.Password)
        dialog.api_key.setText("typed-secret")
        dialog.api_key_toggle.click()
        self.assertEqual(dialog.api_key.text(), "typed-secret")
        self.assertEqual(dialog.api_key.echoMode(), QLineEdit.EchoMode.Normal)
        self.assertEqual(dialog.api_key_toggle.text(), "隐藏")
        dialog.api_key_toggle.click()
        self.assertEqual(dialog.api_key.echoMode(), QLineEdit.EchoMode.Password)
        self.assertEqual(dialog.api_key_toggle.text(), "显示")
        dialog.close()

    def test_diagnostics_are_structured_bounded_and_redacted(self):
        stream = io.StringIO()
        logger = logging.getLogger("qgis_copilot.goal5_test")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        diagnostics = DiagnosticsLogger(logger)
        diagnostics.event(
            "tool:inspect_layer",
            status="success",
            duration_ms=12,
            summary="Authorization: Bearer typed-secret api_key=another-secret",
        )
        logged = stream.getvalue()
        self.assertIn('"event": "tool:inspect_layer"', logged)
        self.assertIn('"duration_ms": 12', logged)
        self.assertNotIn("typed-secret", logged)
        self.assertNotIn("another-secret", logged)
        self.assertIn("[REDACTED]", logged)
        logger.removeHandler(handler)

    def test_redaction_handles_error_text(self):
        safe = redact_text("Bearer typed-secret password=another-secret")
        self.assertNotIn("typed-secret", safe)
        self.assertNotIn("another-secret", safe)

    def test_plugin_zip_is_clean_single_root_and_installable_structure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "qgis_copilot.zip"
            members = build_plugin_zip(PROJECT_ROOT, output)
            self.assertTrue(output.is_file())
            self.assertIn("qgis_copilot/metadata.txt", members)
            self.assertIn("qgis_copilot/__init__.py", members)
            self.assertIn("qgis_copilot/LICENSE", members)
            validate_plugin_zip(output)
            with ZipFile(output) as archive:
                names = archive.namelist()
            self.assertTrue(all(name.startswith("qgis_copilot/") for name in names))
            self.assertFalse(any("references/" in name or "tests/" in name for name in names))
            self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in names))


if __name__ == "__main__":
    unittest.main()
