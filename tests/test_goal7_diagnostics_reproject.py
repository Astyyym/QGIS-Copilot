"""Goal 7 diagnostics and reprojection tests in QGIS bundled runtime."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qgis.core import QgsApplication, QgsFeature, QgsField, QgsProject, QgsRasterLayer, QgsVectorLayer
from qgis.PyQt.QtCore import QEventLoop, QVariant, QTimer
from qgis.PyQt.QtGui import QImage

from qgis_copilot.tools.contracts import PermissionLevel
from qgis_copilot.tools.qgis_tools import create_default_registry
from qgis_copilot.tools.diagnostics_tools import (check_crs_consistency, get_layer_statistics,
    get_project_diagnostics, select_by_expression_preview, selection_summary, validate_layer)
from qgis_copilot.tools.processing_tools import plan_reproject


class GoalSevenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication([], False)
        cls.app.initQgis()
        plugin_path = os.environ.get("QGIS_PLUGIN_PATH")
        if not plugin_path:
            plugin_path = str(Path(cls.app.prefixPath()) / "python" / "plugins")
        if plugin_path not in sys.path:
            sys.path.insert(0, plugin_path)
        from processing.core.Processing import Processing
        Processing.initialize()

    @classmethod
    def tearDownClass(cls):
        cls.app.exitQgis()

    def setUp(self):
        self.project = QgsProject.instance(); self.project.clear()
        self.layer = QgsVectorLayer("Point?crs=EPSG:4326", "stations", "memory")
        provider = self.layer.dataProvider(); provider.addAttributes([QgsField("name", QVariant.String), QgsField("value", QVariant.Double)])
        self.layer.updateFields()
        for i, value in enumerate((1.0, None, 3.0)):
            f = QgsFeature(self.layer.fields()); f.setAttributes([f"S{i}", value])
            from qgis.core import QgsGeometry
            f.setGeometry(QgsGeometry.fromWkt(f"POINT({120+i} {30+i})")); provider.addFeature(f)
        self.layer.updateExtents(); self.project.addMapLayer(self.layer)

    def tearDown(self): self.project.clear()

    def test_diagnostics_crs_quality_statistics_expression_and_selection_are_read_only(self):
        self.layer.selectByIds([self.layer.getFeature(1).id()])
        before = list(self.layer.selectedFeatureIds()); registry = create_default_registry()
        result = get_project_diagnostics({"project": self.project})
        self.assertFalse(result["project"]["saved"]); self.assertTrue(result["risks"])
        crs = check_crs_consistency({"project": self.project})
        self.assertTrue(crs["consistent"]); self.assertEqual(crs["distinct_crs"], ["EPSG:4326"])
        quality = validate_layer({"project": self.project, "layer_id": self.layer.id()})
        self.assertEqual(quality["feature_count"], 3); self.assertEqual(quality["empty_geometry_count"], 0)
        stats = get_layer_statistics({"project": self.project, "layer_id": self.layer.id(), "field": "value"})
        self.assertEqual(stats["null_count"], 1); self.assertEqual(stats["numeric"]["min"], 1.0)
        preview = select_by_expression_preview({"project": self.project, "layer_id": self.layer.id(), "expression": '"value" > 1'})
        self.assertEqual(preview["matched_count"], 1); self.assertFalse(preview["selection_changed"])
        selected = selection_summary({"project": self.project, "layer_id": self.layer.id()})
        self.assertEqual(selected["selected_count"], 1); self.assertEqual(list(self.layer.selectedFeatureIds()), before)
        names = {x["function"]["name"] for x in registry.discover()}
        self.assertTrue({"get_project_diagnostics", "check_crs_consistency", "validate_layer", "get_layer_statistics", "validate_expression", "select_by_expression_preview", "selection_summary"} <= names)
        diagnostic_names = {"get_project_diagnostics", "check_crs_consistency", "validate_layer", "get_layer_statistics", "validate_expression", "select_by_expression_preview", "selection_summary"}
        self.assertTrue(all(x["permission"] == PermissionLevel.READ_ONLY.value for x in registry.discover() if x["function"]["name"] in diagnostic_names))

    def test_raster_diagnostic_is_explicitly_bounded(self):
        path = Path(tempfile.gettempdir()) / "goal7_test.pgm"
        path.write_text("ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 1\nNODATA_value -9999\n0 1\n2 3\n", encoding="ascii")
        raster = QgsRasterLayer(str(path), "tiny raster", "gdal"); self.assertTrue(raster.isValid()); self.project.addMapLayer(raster)
        result = validate_layer({"project": self.project, "layer_id": raster.id()})
        self.assertEqual(result["layer_type"], "raster"); self.assertIn("fields", result["vector_checks_not_applicable"])
        self.project.removeMapLayer(raster.id()); del raster
        path.unlink(missing_ok=True)

    def test_reproject_plan_has_zero_side_effects_and_rejects_ambiguous_or_conflicting_targets(self):
        before = set(self.project.mapLayers()); before_count = self.layer.featureCount()
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / "stations_3857.gpkg"
            plan = plan_reproject({"project": self.project, "layer_id": self.layer.id(), "target_crs": "EPSG:3857", "output_path": str(output)})
            self.assertEqual(plan["source_crs"], "EPSG:4326"); self.assertEqual(plan["target_crs"], "EPSG:3857")
            self.assertFalse(output.exists()); self.assertEqual(set(self.project.mapLayers()), before); self.assertEqual(self.layer.featureCount(), before_count)
            with self.assertRaisesRegex(ValueError, "目标 CRS 无效"):
                plan_reproject({"project": self.project, "layer_id": self.layer.id(), "target_crs": "not-crs", "output_path": str(Path(d)/"x.gpkg")})
            output.write_text("conflict", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "已存在"):
                plan_reproject({"project": self.project, "layer_id": self.layer.id(), "target_crs": "EPSG:3857", "output_path": str(output)})

    def test_confirmed_reproject_creates_reopenable_output_and_preserves_source(self):
        from qgis_copilot.tasks.processing import ReprojectProcessingTask
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / "stations_3857.gpkg"
            plan = plan_reproject({"project": self.project, "layer_id": self.layer.id(), "target_crs": "EPSG:3857", "output_path": str(output)})
            before_ids = set(self.project.mapLayers()); before_count = self.layer.featureCount()
            task = ReprojectProcessingTask(plan); received = {"result": None, "error": None, "cancelled": False}; loop = QEventLoop()
            task.completed.connect(lambda value: (received.__setitem__("result", value), loop.quit()))
            task.failed.connect(lambda value: (received.__setitem__("error", value), loop.quit()))
            task.cancelled.connect(lambda: (received.__setitem__("cancelled", True), loop.quit()))
            task.start(); timer = QTimer(); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(15000); loop.exec()
            self.assertTrue(timer.isActive(), "重投影任务超过 15 秒未完成"); timer.stop()
            self.assertIsNone(received["error"], received["error"]); self.assertFalse(received["cancelled"]); self.assertTrue(output.is_file())
            result = received["result"]; self.assertIsNotNone(result); self.assertEqual(result["target_crs"], "EPSG:3857"); self.assertEqual(self.layer.featureCount(), before_count)
            self.assertEqual(set(self.project.mapLayers()) - before_ids, {result["output_layer_id"]})
            out = self.project.mapLayer(result["output_layer_id"]); self.assertTrue(out.isValid()); self.assertEqual(out.crs().authid(), "EPSG:3857"); self.assertEqual(out.featureCount(), before_count)
            self.project.removeMapLayer(out.id()); del out


if __name__ == "__main__": unittest.main()
