"""Goal 6 transparent workbench and capability-profile regression tests."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from qgis.core import QgsApplication, QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtWidgets import QApplication, QToolButton

from qgis_copilot.application.controller import ApplicationController
from qgis_copilot.models.capabilities import BehaviorMode, REASONING_EFFORT_COMPATIBLE, STANDARD_OPENAI_COMPATIBLE
from qgis_copilot.models.openai_compatible import OpenAICompatibleAdapter
from qgis_copilot.models.request_options import build_request_options
from qgis_copilot.models.settings import ModelSettings, ModelSettingsStore
from qgis_copilot.ui.chat_dock import ChatDockWidget
from qgis_copilot.ui.settings_dialog import SettingsDialog
from qgis_copilot.ui.view_models import ToolCard, WorkbenchStage
from qgis_copilot.tools.processing_tools import plan_reproject


class _Response:
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def read(self): return b'{"model":"demo","choices":[{"message":{"content":"ok"}}]}'


class GoalSixWorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.qgis = QgsApplication.instance() or QgsApplication([], False)
        if not QgsApplication.instance(): cls.qgis.initQgis()

    def setUp(self):
        QgsProject.instance().clear()

    def test_standard_profile_sends_no_private_behavior_field(self):
        self.assertEqual(build_request_options(STANDARD_OPENAI_COMPATIBLE, BehaviorMode.SERVICE_DEFAULT), {})
        self.assertEqual(build_request_options(REASONING_EFFORT_COMPATIBLE, BehaviorMode.DEEP), {"reasoning_effort": "high"})
        captured = {}
        def fake_urlopen(request, timeout):
            captured.update(json.loads(request.data.decode("utf-8"))); return _Response()
        settings = ModelSettings("https://example.test/v1", "demo", capability_profile_id="standard_openai_compatible")
        with patch("qgis_copilot.models.openai_compatible.request.urlopen", fake_urlopen):
            OpenAICompatibleAdapter(settings, "test-secret").complete([{"role":"user","content":"x"}], Event())
        self.assertNotIn("reasoning_effort", captured)

    def test_supported_profile_sends_declared_field_only(self):
        captured = {}
        def fake_urlopen(request, timeout):
            captured.update(json.loads(request.data.decode("utf-8"))); return _Response()
        settings = ModelSettings("https://example.test/v1", "demo", capability_profile_id="reasoning_effort_compatible", behavior_mode="fast")
        with patch("qgis_copilot.models.openai_compatible.request.urlopen", fake_urlopen):
            OpenAICompatibleAdapter(settings, "test-secret").complete([{"role":"user","content":"x"}], Event())
        self.assertEqual(captured.get("reasoning_effort"), "low")
        self.assertNotIn("api_key", captured)

    def test_settings_persist_no_secret_and_disable_unsupported_mode(self):
        store = ModelSettingsStore(QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "goal6", "settings"))
        store.clear(); settings = ModelSettings("https://example.test/v1", "demo", capability_profile_id="standard_openai_compatible")
        store.save(settings); loaded = store.load()
        self.assertEqual(loaded.capability_profile.profile_id, "standard_openai_compatible")
        dialog = SettingsDialog(loaded)
        self.assertFalse(dialog.behavior_mode.isEnabled())
        self.assertIn("服务端控制推理", dialog.behavior_hint.text())
        self.assertEqual(dialog.api_key.text(), "")
        dialog.close(); store.clear()

    def test_session_info_shortcuts_cards_and_audit_are_real_ui_state(self):
        dock = ChatDockWidget(); controller = ApplicationController(dock); controller.activate()
        self.assertIn("未命名项目", dock.session_info.text())
        self.assertIn("未配置", dock.session_info.text())
        self.assertIn("只读；写入需确认", dock.session_info.text())
        dock.input.clear(); dock.quick_tasks.findChildren(QToolButton)[0].click()
        self.assertTrue(dock.input.text())
        dock.add_tool_card(ToolCard("list_layers", "图层数：0。", '{"bounded": true}', actions=()))
        detail = dock.audit_detail
        dock.set_audit_record(["模型：demo", "完成：无写入"])
        self.assertIn("无写入", detail.text())
        dock.set_stage(WorkbenchStage.WAITING_CONFIRMATION)
        self.assertIn("尚未写入", dock.status_label.text())
        dock.close()

    def test_new_session_clears_history_and_reenables_plan_controls(self):
        dock = ChatDockWidget(); controller = ApplicationController(dock); controller.activate()
        controller._agent.begin("旧问题", {"layers": []})
        controller._audit_lines = ["旧审计"]
        dock.append_message(controller.view_model.add_message("user", "旧问题"))
        controller.new_session()
        self.assertEqual(len(controller._agent._conversation.request_messages()), 1)
        self.assertFalse(controller._audit_lines)
        self.assertFalse(dock.empty_label.isHidden())
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "stations", "memory")
        QgsProject.instance().addMapLayer(layer)
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = plan_reproject({"layer_id": layer.id(), "target_crs": "EPSG:3857", "output_path": str(Path(temp_dir) / "new.gpkg")})
            dock.set_plan_controls_enabled(False); dock.show_execution_plan(plan); dock.set_plan_controls_enabled(True)
            self.assertTrue(dock.plan_confirm_button.isEnabled())
            self.assertTrue(dock.plan_cancel_button.isEnabled())
        dock.close()

    def test_session_history_stays_in_memory_and_switches_views(self):
        dock = ChatDockWidget(); controller = ApplicationController(dock); controller.activate()
        dock.append_message(controller.view_model.add_message("user", "会话一的问题")); controller._audit_lines = ["会话一审计"]
        controller.new_session(); dock.append_message(controller.view_model.add_message("user", "会话二的问题"))
        self.assertEqual(dock.session_selector.count(), 2)
        controller.switch_session(0)
        self.assertIn("会话一的问题", " ".join(widget.text() for widget in dock._message_widgets)); self.assertIn("会话一审计", dock.audit_detail.text())
        controller.switch_session(1)
        self.assertIn("会话二的问题", " ".join(widget.text() for widget in dock._message_widgets)); self.assertNotIn("会话一的问题", " ".join(widget.text() for widget in dock._message_widgets))
        dock.close()

    def test_result_actions_call_real_qgis_interface_or_fail_safely_when_stale(self):
        dock = ChatDockWidget(); controller = ApplicationController(dock)
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "stations", "memory")
        QgsProject.instance().addMapLayer(layer)
        fake_iface = MagicMock(); fake_canvas = MagicMock(); fake_iface.mapCanvas.return_value = fake_canvas
        with patch("qgis_copilot.application.controller.qgis_iface", fake_iface):
            controller.zoom_to_layer(layer.id())
            fake_canvas.setExtent.assert_called_once()
            fake_canvas.refresh.assert_called_once()
            controller.open_attribute_table(layer.id())
            fake_iface.showAttributeTable.assert_called_once_with(layer)
        actions = controller._result_actions({"data": {"layer_id": layer.id()}})
        self.assertEqual([action.kind for action in actions], ["zoom_layer", "open_attributes"])
        layer_id = layer.id()
        QgsProject.instance().removeMapLayer(layer_id)
        controller.zoom_to_layer(layer_id)
        self.assertIn("目标图层已不存在", dock.status_label.text())
        dock.close()

    def test_intersection_plan_renders_two_inputs_without_ui_error(self):
        dock = ChatDockWidget()
        plan = {
            "tool": "intersection", "inputs": {
                "input_layer_name": "ShortLength", "input_feature_count": 31,
                "overlay_layer_name": "shenzhen_auto_roads", "overlay_feature_count": 8,
            }, "parameters": {"algorithm": "native:intersection"},
            "output_path": "D:/Temp/intersection.gpkg", "impact": "只创建新结果。", "risks": ["CRS 已校验。"],
        }
        dock.show_execution_plan(plan)
        self.assertFalse(dock.plan_card.isHidden())
        self.assertIn("ShortLength", dock.plan_detail.text())
        self.assertIn("shenzhen_auto_roads", dock.plan_detail.text())
        dock.close()


if __name__ == "__main__":
    unittest.main()
