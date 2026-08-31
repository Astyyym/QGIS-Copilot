"""Goal 8 spatial preview, clip and filtered-export regression in QGIS runtime."""
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
from qgis_copilot.tools.processing_tools import plan_clip_vector, plan_export_filtered_features
from qgis_copilot.tools.qgis_tools import create_default_registry
from qgis_copilot.tools.query_tools import spatial_query_preview


class GoalEightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication([], False); cls.app.initQgis()
        plugin_path = os.environ.get("QGIS_PLUGIN_PATH") or str(Path(cls.app.prefixPath()) / "python" / "plugins")
        if plugin_path not in sys.path: sys.path.insert(0, plugin_path)
        from processing.core.Processing import Processing
        Processing.initialize()

    @classmethod
    def tearDownClass(cls): cls.app.exitQgis()

    def setUp(self):
        self.project = QgsProject.instance(); self.project.clear()
        self.points = QgsVectorLayer("Point?crs=EPSG:3857", "points", "memory")
        provider = self.points.dataProvider(); provider.addAttributes([QgsField("kind", QVariant.String)]); self.points.updateFields()
        for x, kind in ((0, "inside"), (5, "inside"), (50, "outside")):
            feature = QgsFeature(self.points.fields()); feature.setAttributes([kind]); feature.setGeometry(QgsGeometry.fromWkt(f"POINT({x} 0)")); provider.addFeature(feature)
        self.points.updateExtents(); self.project.addMapLayer(self.points)
        self.mask = QgsVectorLayer("Polygon?crs=EPSG:3857", "mask", "memory")
        feature = QgsFeature(); feature.setGeometry(QgsGeometry.fromWkt("POLYGON((-10 -10, 10 -10, 10 10, -10 10, -10 -10))")); self.mask.dataProvider().addFeature(feature); self.mask.updateExtents(); self.project.addMapLayer(self.mask)

    def tearDown(self): self.project.clear()

    def _wait_task(self, task):
        received = {"result": None, "error": None, "cancelled": False}; loop = QEventLoop()
        task.completed.connect(lambda value: (received.__setitem__("result", value), loop.quit()))
        task.failed.connect(lambda value: (received.__setitem__("error", value), loop.quit()))
        task.cancelled.connect(lambda: (received.__setitem__("cancelled", True), loop.quit()))
        task.start(); timer = QTimer(); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(15000); loop.exec()
        self.assertTrue(timer.isActive(), "Processing 超过 15 秒未完成"); timer.stop(); return received

    def test_preview_is_read_only_bounded_and_registered(self):
        self.points.selectByIds([self.points.getFeature(1).id()]); before_selection = list(self.points.selectedFeatureIds()); before_layers = set(self.project.mapLayers())
        result = spatial_query_preview({"project": self.project, "input_layer_id": self.points.id(), "reference_layer_id": self.mask.id(), "relation": "intersects"})
        self.assertEqual(result["matched_count"], 2); self.assertFalse(result["selection_changed"]); self.assertFalse(result["project_changed"])
        self.assertEqual(before_selection, list(self.points.selectedFeatureIds())); self.assertEqual(before_layers, set(self.project.mapLayers()))
        with self.assertRaisesRegex(ValueError, "CRS 不一致"):
            other = QgsVectorLayer("Polygon?crs=EPSG:4326", "other", "memory"); self.project.addMapLayer(other)
            spatial_query_preview({"project": self.project, "input_layer_id": self.points.id(), "reference_layer_id": other.id(), "relation": "intersects"})
        registry = create_default_registry(); specs = {item["function"]["name"]: item for item in registry.discover()}
        self.assertEqual(specs["spatial_query_preview"]["permission"], PermissionLevel.READ_ONLY.value)
        self.assertEqual(specs["clip_vector"]["permission"], PermissionLevel.WRITE.value)
        self.assertEqual(specs["export_filtered_features"]["permission"], PermissionLevel.WRITE.value)

    def test_clip_plan_is_side_effect_free_and_confirmed_output_is_reopenable(self):
        from qgis_copilot.tasks.processing import VectorProcessingTask
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "clip.gpkg"; before_ids = set(self.project.mapLayers()); before_count = self.points.featureCount()
            plan = plan_clip_vector({"project": self.project, "input_layer_id": self.points.id(), "mask_layer_id": self.mask.id(), "output_path": str(output)})
            self.assertFalse(output.exists()); self.assertEqual(before_ids, set(self.project.mapLayers()))
            received = self._wait_task(VectorProcessingTask(plan))
            result = received["result"]; self.assertIsNone(received["error"], received["error"]); self.assertTrue(output.is_file()); self.assertEqual(result["feature_count"], 2)
            self.assertEqual(self.points.featureCount(), before_count); self.assertEqual(set(self.project.mapLayers()) - before_ids, {result["output_layer_id"]})
            self.project.removeMapLayer(result["output_layer_id"])
            with self.assertRaisesRegex(ValueError, "已存在"):
                plan_clip_vector({"project": self.project, "input_layer_id": self.points.id(), "mask_layer_id": self.mask.id(), "output_path": str(output)})

    def test_expression_export_plan_rejects_empty_and_confirmed_output_preserves_sources(self):
        from qgis_copilot.tasks.processing import VectorProcessingTask
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "filtered.gpkg"; before_ids = set(self.project.mapLayers()); before_selection = list(self.points.selectedFeatureIds())
            plan = plan_export_filtered_features({"project": self.project, "layer_id": self.points.id(), "filter_kind": "expression", "expression": '"kind" = \'inside\'', "output_path": str(output)})
            self.assertEqual(plan["parameters"]["estimated_feature_count"], 2); self.assertFalse(output.exists())
            received = self._wait_task(VectorProcessingTask(plan))
            result = received["result"]; self.assertIsNone(received["error"], received["error"]); self.assertTrue(output.is_file()); self.assertEqual(result["feature_count"], 2)
            self.assertEqual(before_selection, list(self.points.selectedFeatureIds())); self.assertEqual(set(self.project.mapLayers()) - before_ids, {result["output_layer_id"]})
            self.project.removeMapLayer(result["output_layer_id"])
            with self.assertRaisesRegex(ValueError, "没有匹配"):
                plan_export_filtered_features({"project": self.project, "layer_id": self.points.id(), "filter_kind": "expression", "expression": '"kind" = \'missing\'', "output_path": str(Path(directory) / "none.gpkg")})


if __name__ == "__main__": unittest.main()
