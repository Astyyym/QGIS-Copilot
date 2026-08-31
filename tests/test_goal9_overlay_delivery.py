"""Goal 9 intersection/dissolve safety regression in the QGIS runtime."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qgis.core import QgsApplication, QgsFeature, QgsField, QgsGeometry, QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QEventLoop, QVariant, QTimer

from qgis_copilot.tools.contracts import PermissionLevel
from qgis_copilot.tools.processing_tools import plan_dissolve, plan_intersection
from qgis_copilot.tools.qgis_tools import create_default_registry


class GoalNineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plugin_path = Path("D:/app/QGIS/apps/qgis/python/plugins")
        if str(plugin_path) not in sys.path:
            sys.path.insert(0, str(plugin_path))
        from processing.core.Processing import Processing
        cls.app = QgsApplication([], False)
        cls.app.initQgis()
        Processing.initialize()

    @classmethod
    def tearDownClass(cls):
        cls.app.exitQgis()

    def setUp(self):
        self.project = QgsProject.instance()
        self.project.clear()
        self.left = QgsVectorLayer("Polygon?crs=EPSG:3857", "left", "memory")
        self.left.dataProvider().addAttributes([QgsField("group", QVariant.String), QgsField("shared", QVariant.String)])
        self.left.updateFields()
        for wkt, group, shared in (
            ("POLYGON((0 0,10 0,10 10,0 10,0 0))", "a", "left"),
            ("POLYGON((20 0,30 0,30 10,20 10,20 0))", "a", "left"),
        ):
            f = QgsFeature(self.left.fields()); f.setAttributes([group, shared]); f.setGeometry(QgsGeometry.fromWkt(wkt)); self.left.dataProvider().addFeature(f)
        self.left.updateExtents(); self.project.addMapLayer(self.left)
        self.right = QgsVectorLayer("Polygon?crs=EPSG:3857", "right", "memory")
        self.right.dataProvider().addAttributes([QgsField("zone", QVariant.String), QgsField("shared", QVariant.String)])
        self.right.updateFields()
        f = QgsFeature(self.right.fields()); f.setAttributes(["x", "right"]); f.setGeometry(QgsGeometry.fromWkt("POLYGON((5 5,15 5,15 15,5 15,5 5))")); self.right.dataProvider().addFeature(f)
        self.right.updateExtents(); self.project.addMapLayer(self.right)

    def tearDown(self):
        self.project.clear()

    def _wait_task(self, task):
        received = {"result": None, "error": None, "cancelled": False}
        loop = QEventLoop()
        task.completed.connect(lambda value: (received.__setitem__("result", value), loop.quit()))
        task.failed.connect(lambda value: (received.__setitem__("error", value), loop.quit()))
        task.cancelled.connect(lambda: (received.__setitem__("cancelled", True), loop.quit()))
        task.start()
        timer = QTimer(); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(15000)
        loop.exec()
        self.assertTrue(timer.isActive(), "Processing 超过 15 秒未完成")
        timer.stop()
        return received

    def test_registry_and_plans_are_explicit_and_side_effect_free(self):
        registry = create_default_registry()
        specs = {item["function"]["name"]: item for item in registry.discover()}
        self.assertEqual(specs["intersection"]["permission"], PermissionLevel.WRITE.value)
        self.assertEqual(specs["dissolve"]["permission"], PermissionLevel.WRITE.value)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "intersection.gpkg"
            before = set(self.project.mapLayers())
            plan = plan_intersection({"project": self.project, "input_layer_id": self.left.id(), "overlay_layer_id": self.right.id(), "output_path": str(output)})
            self.assertFalse(output.exists())
            self.assertEqual(before, set(self.project.mapLayers()))
            self.assertEqual(plan["parameters"]["algorithm"], "native:intersection")
            self.assertEqual(plan["parameters"]["field_conflicts"], ["shared"])
            self.assertEqual(plan["parameters"]["overlay_prefix"], "overlay_")
            with self.assertRaisesRegex(ValueError, "必须明确"):
                plan_dissolve({"project": self.project, "layer_id": self.left.id(), "output_path": str(Path(directory) / "bad.gpkg")})
            with self.assertRaisesRegex(ValueError, "同名字段"):
                plan_intersection({"project": self.project, "input_layer_id": self.left.id(), "overlay_layer_id": self.right.id(), "overlay_prefix": "", "output_path": str(Path(directory) / "bad2.gpkg")})

    def test_controller_dispatches_new_tools_to_shared_vector_task(self):
        from qgis_copilot.application.controller import VectorProcessingTask as ControllerVectorTask
        self.assertIs(ControllerVectorTask, __import__("qgis_copilot.tasks.processing", fromlist=["VectorProcessingTask"]).VectorProcessingTask)

    def test_intersection_confirmed_output_reopens_and_sources_unchanged(self):
        from qgis_copilot.tasks.processing import VectorProcessingTask
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "intersection.gpkg"
            before_ids = set(self.project.mapLayers()); left_count = self.left.featureCount(); right_count = self.right.featureCount()
            plan = plan_intersection({"project": self.project, "input_layer_id": self.left.id(), "overlay_layer_id": self.right.id(), "output_path": str(output)})
            received = self._wait_task(VectorProcessingTask(plan))
            self.assertIsNone(received["error"], received["error"])
            result = received["result"]
            self.assertTrue(output.is_file()); self.assertEqual(result["feature_count"], 1)
            reopened = QgsVectorLayer(str(output), "reopened", "ogr")
            self.assertTrue(reopened.isValid()); self.assertEqual(reopened.featureCount(), 1)
            self.assertEqual(self.left.featureCount(), left_count); self.assertEqual(self.right.featureCount(), right_count)
            self.assertEqual(set(self.project.mapLayers()) - before_ids, {result["output_layer_id"]})
            self.project.removeMapLayer(result["output_layer_id"])
            del reopened
            with self.assertRaisesRegex(ValueError, "已存在"):
                plan_intersection({"project": self.project, "input_layer_id": self.left.id(), "overlay_layer_id": self.right.id(), "output_path": str(output)})

    def test_dissolve_by_field_and_full_dissolve(self):
        from qgis_copilot.tasks.processing import VectorProcessingTask
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dissolve.gpkg"
            plan = plan_dissolve({"project": self.project, "layer_id": self.left.id(), "dissolve_field": "group", "output_path": str(output)})
            before = self.left.featureCount(); received = self._wait_task(VectorProcessingTask(plan))
            self.assertIsNone(received["error"], received["error"]); self.assertEqual(received["result"]["feature_count"], 1)
            self.assertEqual(self.left.featureCount(), before); self.project.removeMapLayer(received["result"]["output_layer_id"])
            with self.assertRaisesRegex(ValueError, "不能由插件猜测"):
                plan_dissolve({"project": self.project, "layer_id": self.left.id(), "dissolve_field": "group", "dissolve_all": True, "output_path": str(Path(directory) / "bad.gpkg")})
            full = plan_dissolve({"project": self.project, "layer_id": self.left.id(), "dissolve_all": True, "output_path": str(Path(directory) / "full.gpkg")})
            received = self._wait_task(VectorProcessingTask(full))
            self.assertIsNone(received["error"], received["error"]); self.assertEqual(received["result"]["feature_count"], 1)
            self.project.removeMapLayer(received["result"]["output_layer_id"])


if __name__ == "__main__":
    unittest.main()
