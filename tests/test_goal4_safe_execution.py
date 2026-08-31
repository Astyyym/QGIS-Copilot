"""Goal 4 plan/confirmation/Processing regression tests in QGIS's bundled runtime."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from qgis.core import QgsApplication, QgsFeature, QgsField, QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QEventLoop, QVariant, QTimer

from qgis_copilot.agent.core import AgentCore
from qgis_copilot.models.base import ChatCompletion, ToolCall
from qgis_copilot.tools.contracts import PermissionLevel, ToolResult
from qgis_copilot.tools.permissions import can_execute, requires_confirmation
from qgis_copilot.tools.qgis_tools import create_default_registry, plan_buffer


class GoalFourSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plugin_path = os.environ.get("QGIS_PLUGIN_PATH")
        if not plugin_path:
            plugin_path = str(Path("D:/app/QGIS") / "apps" / "qgis" / "python" / "plugins")
        if plugin_path and plugin_path not in sys.path:
            sys.path.insert(0, plugin_path)
        from processing.core.Processing import Processing
        cls.qgis = QgsApplication([], False)
        cls.qgis.initQgis()
        Processing.initialize()
        if QgsApplication.processingRegistry().algorithmById("native:buffer") is None:
            raise RuntimeError("native:buffer unavailable after Processing initialization")

    @classmethod
    def tearDownClass(cls):
        cls.qgis.exitQgis()

    def setUp(self):
        self.project = QgsProject.instance()
        self.project.clear()
        self.roads = QgsVectorLayer("LineString?crs=EPSG:3857", "roads", "memory")
        provider = self.roads.dataProvider()
        provider.addAttributes([QgsField("name", QVariant.String)])
        self.roads.updateFields()
        feature = QgsFeature(self.roads.fields())
        feature.setAttributes(["Main St"])
        feature.setGeometry(__import__("qgis.core", fromlist=["QgsGeometry"]).QgsGeometry.fromWkt("LINESTRING(0 0, 1000 0)"))
        provider.addFeature(feature)
        self.roads.updateExtents()
        self.project.addMapLayer(self.roads)

    def tearDown(self):
        self.project.clear()

    def test_write_tool_requires_confirmation_and_exposes_plan_schema(self):
        registry = create_default_registry()
        spec = registry.get("buffer_vector")
        self.assertEqual(spec.permission, PermissionLevel.WRITE)
        self.assertTrue(requires_confirmation(spec))
        self.assertFalse(can_execute(spec))
        self.assertTrue(can_execute(spec, confirmed=True))
        schema = next(item for item in registry.discover() if item["function"]["name"] == "buffer_vector")
        self.assertEqual(schema["permission"], "write")
        self.assertIn("output_path", schema["function"]["parameters"]["properties"])

    def test_plan_does_not_create_file_or_change_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "result.gpkg"
            before_ids = sorted(self.project.mapLayers())
            plan = plan_buffer({"project": self.project, "layer_id": self.roads.id(), "distance": 500, "output_path": str(output)})
            self.assertFalse(output.exists())
            self.assertEqual(sorted(self.project.mapLayers()), before_ids)
            self.assertEqual(plan["inputs"]["layer_id"], self.roads.id())
            self.assertEqual(plan["parameters"]["distance"], 500.0)
            self.assertEqual(plan["parameters"]["distance_unit"], "米")
            self.assertFalse(plan["needs_metric_reprojection"])
            self.assertIn("不会编辑原始图层", plan["impact"])
            self.assertIn("OUTPUT", plan["processing_parameters"])

    def test_wgs84_plan_promises_metric_reprojection(self):
        geographic = QgsVectorLayer("Point?crs=EPSG:4326", "stations_wgs84", "memory")
        provider = geographic.dataProvider()
        provider.addAttributes([QgsField("name", QVariant.String)])
        geographic.updateFields()
        feature = QgsFeature(geographic.fields())
        feature.setAttributes(["Station A"])
        feature.setGeometry(__import__("qgis.core", fromlist=["QgsGeometry"]).QgsGeometry.fromWkt("POINT(90 30)"))
        provider.addFeature(feature)
        geographic.updateExtents()
        self.project.addMapLayer(geographic)
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = plan_buffer({"project": self.project, "layer_id": geographic.id(), "distance": 500, "output_path": str(Path(temp_dir) / "wgs84_buffer.gpkg")})
            self.assertTrue(plan["needs_metric_reprojection"])
            self.assertEqual(plan["source_crs"], "EPSG:4326")
            self.assertIn("临时投影到 EPSG:3857", " ".join(plan["risks"]))

    def test_existing_file_unsaved_project_and_invalid_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            existing = Path(temp_dir) / "exists.gpkg"
            existing.write_text("not overwritten", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "已存在"):
                plan_buffer({"project": self.project, "layer_id": self.roads.id(), "distance": 500, "output_path": str(existing)})
            with self.assertRaisesRegex(ValueError, "必须大于 0"):
                plan_buffer({"project": self.project, "layer_id": self.roads.id(), "distance": 0, "output_path": str(Path(temp_dir) / "zero.gpkg")})
            with self.assertRaisesRegex(ValueError, "必须是新的 .gpkg"):
                plan_buffer({"project": self.project, "layer_id": self.roads.id(), "distance": 1, "output_path": str(Path(temp_dir) / "wrong.geojson")})
        unsaved = QgsProject()
        unsaved.addMapLayer(self.roads)
        with self.assertRaisesRegex(ValueError, "尚未保存"):
            plan_buffer({"project": unsaved, "layer_id": self.roads.id(), "distance": 1})

    def test_registry_plan_call_never_executes_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "registry.gpkg"
            registry = create_default_registry()
            result = registry.call("buffer_vector", {"project": self.project, "layer_id": self.roads.id(), "distance": 50, "output_path": str(output)})
            self.assertTrue(result.ok, result.error)
            self.assertFalse(output.exists())
            self.assertEqual(result.data["tool"], "buffer_vector")

    def test_plan_tool_call_is_paired_before_waiting_for_confirmation(self):
        agent = AgentCore("system", max_steps=3, tool_registry=create_default_registry())
        agent.begin("创建道路缓冲区", {"layers": []})
        call = ToolCall("call-plan", "buffer_vector", {"layer_id": self.roads.id(), "distance": 50})
        agent.accept_completion(ChatCompletion("", tool_calls=(call,)))
        # Goal 4 pauses after plan generation, but must already save this exact
        # tool_call_id so the next user request cannot contain an orphaned call.
        agent.accept_tool_result(call, ToolResult("buffer_vector", True, {"title": "待确认计划", "output_path": "new.gpkg"}))
        messages = agent._conversation.request_messages()
        assistant = next(message for message in messages if message["role"] == "assistant")
        tool = next(message for message in messages if message["role"] == "tool")
        self.assertEqual(assistant["tool_calls"][0]["id"], tool["tool_call_id"])
        self.assertEqual(tool["name"], "buffer_vector")

    def test_failed_tool_call_is_paired_before_the_next_user_turn(self):
        agent = AgentCore("system", max_steps=3, tool_registry=create_default_registry())
        agent.begin("创建道路缓冲区", {"layers": []})
        call = ToolCall("call-failed-plan", "buffer_vector", {"layer_id": self.roads.id(), "distance": 50})
        agent.accept_completion(ChatCompletion("", tool_calls=(call,)))
        agent.accept_tool_result(call, ToolResult("buffer_vector", False, {}, "参数无效：输出文件已存在。"))
        messages = agent._conversation.request_messages()
        assistant = next(message for message in messages if message["role"] == "assistant")
        tool = next(message for message in messages if message["role"] == "tool")
        self.assertEqual(assistant["tool_calls"][0]["id"], tool["tool_call_id"])
        self.assertFalse(__import__("json").loads(tool["content"])["ok"])

    def test_confirmed_processing_creates_reopenable_layer_without_source_mutation(self):
        from qgis_copilot.tasks.processing import BufferProcessingTask
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "confirmed.gpkg"
            plan = plan_buffer({"project": self.project, "layer_id": self.roads.id(), "distance": 50, "output_path": str(output)})
            before_ids = sorted(self.project.mapLayers())
            before_count = self.roads.featureCount()
            task = BufferProcessingTask(plan)
            received = {"result": None, "error": None, "cancelled": False}
            loop = QEventLoop()
            task.completed.connect(lambda result: (received.__setitem__("result", result), loop.quit()))
            task.failed.connect(lambda error: (received.__setitem__("error", error), loop.quit()))
            task.cancelled.connect(lambda: (received.__setitem__("cancelled", True), loop.quit()))
            task.start()
            timeout = QTimer()
            timeout.setSingleShot(True)
            timeout.timeout.connect(loop.quit)
            timeout.start(15000)
            loop.exec()
            self.assertTrue(timeout.isActive(), "Processing 任务超过 15 秒未完成")
            timeout.stop()
            self.assertIsNone(received["error"], received["error"])
            self.assertFalse(received["cancelled"])
            self.assertTrue(output.is_file())
            self.assertIsNotNone(received["result"])
            output_layer_id = received["result"]["output_layer_id"]
            self.assertIn(output_layer_id, self.project.mapLayers())
            self.assertEqual(self.roads.featureCount(), before_count)
            self.assertEqual(set(before_ids), set(self.project.mapLayers()) - {output_layer_id})
            self.project.removeMapLayer(output_layer_id)
    def test_confirmed_geographic_processing_uses_meter_path_and_restores_crs(self):
        from qgis_copilot.tasks.processing import BufferProcessingTask
        geographic = QgsVectorLayer("Point?crs=EPSG:4326", "stations_wgs84", "memory")
        provider = geographic.dataProvider()
        provider.addAttributes([QgsField("name", QVariant.String)])
        geographic.updateFields()
        feature = QgsFeature(geographic.fields())
        feature.setAttributes(["Station A"])
        feature.setGeometry(__import__("qgis.core", fromlist=["QgsGeometry"]).QgsGeometry.fromWkt("POINT(90 30)"))
        provider.addFeature(feature)
        geographic.updateExtents()
        self.project.addMapLayer(geographic)
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "wgs84_confirmed.gpkg"
            plan = plan_buffer({"project": self.project, "layer_id": geographic.id(), "distance": 500, "output_path": str(output)})
            task = BufferProcessingTask(plan)
            received = {"result": None, "error": None}
            loop = QEventLoop()
            task.completed.connect(lambda result: (received.__setitem__("result", result), loop.quit()))
            task.failed.connect(lambda error: (received.__setitem__("error", error), loop.quit()))
            task.start()
            timeout = QTimer()
            timeout.setSingleShot(True)
            timeout.timeout.connect(loop.quit)
            timeout.start(15000)
            loop.exec()
            self.assertTrue(timeout.isActive(), "地理 CRS 缓冲区任务超过 15 秒未完成")
            timeout.stop()
            self.assertIsNone(received["error"], received["error"])
            self.assertTrue(output.is_file())
            self.assertTrue(received["result"]["metric_reprojection"])
            output_layer = self.project.mapLayer(received["result"]["output_layer_id"])
            self.assertEqual(output_layer.crs().authid(), "EPSG:4326")
            self.project.removeMapLayer(output_layer.id())


if __name__ == "__main__":
    unittest.main()
