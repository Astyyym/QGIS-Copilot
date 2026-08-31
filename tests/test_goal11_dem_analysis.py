"""Goal 11 slope vertical-slice regression; run with QGIS bundled Python."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import gc
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsProject, QgsRasterLayer
from qgis.PyQt.QtCore import QEventLoop, QTimer

from qgis_copilot.tools.contracts import PermissionLevel
from qgis_copilot.tools.qgis_tools import create_default_registry
from qgis_copilot.tools.raster.dem_plans import plan_slope_from_dem


class GoalElevenDemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication([], False)
        cls.app.initQgis()
        plugin_path = os.environ.get("QGIS_PLUGIN_PATH") or str(Path(cls.app.prefixPath()) / "python" / "plugins")
        if plugin_path not in sys.path:
            sys.path.insert(0, plugin_path)
        from processing.core.Processing import Processing
        Processing.initialize()
        if QgsApplication.processingRegistry().algorithmById("gdal:slope") is None:
            raise unittest.SkipTest("目标 QGIS 未提供 gdal:slope")

    @classmethod
    def tearDownClass(cls):
        cls.app.exitQgis()

    def setUp(self):
        self.project = QgsProject.instance(); self.project.clear()

    def tearDown(self):
        self.project.clear()

    def _dem(self, directory: str):
        path = Path(directory) / "plane.asc"
        path.write_text("ncols 3\nnrows 3\nxllcorner 0\nyllcorner 0\ncellsize 10\nNODATA_value -9999\n0 10 20\n0 10 20\n0 10 20\n", encoding="ascii")
        path.with_suffix(".prj").write_text(QgsCoordinateReferenceSystem("EPSG:3857").toWkt(), encoding="ascii")
        layer = QgsRasterLayer(str(path), "plane DEM", "gdal")
        self.assertTrue(layer.isValid(), layer.error().message())
        layer.setCrs(QgsCoordinateReferenceSystem("EPSG:3857")); self.project.addMapLayer(layer)
        return layer

    def _geographic_dem(self, directory: str):
        path = Path(directory) / "geographic.asc"
        path.write_text("ncols 3\nnrows 3\nxllcorner 114\nyllcorner 22\ncellsize 0.001\nNODATA_value -9999\n0 10 20\n0 10 20\n0 10 20\n", encoding="ascii")
        path.with_suffix(".prj").write_text(QgsCoordinateReferenceSystem("EPSG:4326").toWkt(), encoding="ascii")
        layer = QgsRasterLayer(str(path), "geographic DEM", "gdal")
        self.assertTrue(layer.isValid(), layer.error().message())
        self.project.addMapLayer(layer)
        return layer

    def _wait(self, task):
        received = {"result": None, "error": None, "cancelled": False}
        loop = QEventLoop()
        task.completed.connect(lambda value: (received.__setitem__("result", value), loop.quit()))
        task.failed.connect(lambda value: (received.__setitem__("error", value), loop.quit()))
        task.cancelled.connect(lambda: (received.__setitem__("cancelled", True), loop.quit()))
        task.start(); timer = QTimer(); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(15000); loop.exec()
        self.assertTrue(timer.isActive(), "坡度 Processing 超过 15 秒未结束"); timer.stop()
        return received

    def test_registry_and_plan_are_explicit_and_side_effect_free(self):
        spec = {item["function"]["name"]: item for item in create_default_registry().discover()}["slope_from_dem"]
        self.assertEqual(spec["permission"], PermissionLevel.WRITE.value)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            layer = self._dem(directory); output = Path(directory) / "slope.tif"; before = set(self.project.mapLayers())
            plan = plan_slope_from_dem({"project": self.project, "layer_id": layer.id(), "elevation_unit": "meters", "horizontal_unit": "meters", "z_factor": 1, "output_path": str(output)})
            self.assertFalse(output.exists()); self.assertEqual(before, set(self.project.mapLayers()))
            self.assertEqual(plan["parameters"]["algorithm"], "gdal:slope"); self.assertEqual(plan["parameters"]["scale"], 1.0)
            self.assertEqual(plan["inputs"]["band"], 1)
            self.project.removeMapLayer(layer.id()); del layer

    def test_rejects_geographic_units_and_existing_output_without_writes(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            layer = self._dem(directory); output = Path(directory) / "exists.tif"; output.write_bytes(b"keep")
            base = {"project": self.project, "layer_id": layer.id(), "elevation_unit": "meters", "horizontal_unit": "meters", "output_path": str(output)}
            with self.assertRaisesRegex(ValueError, "已存在"):
                plan_slope_from_dem(base)
            self.assertEqual(output.read_bytes(), b"keep")
            with self.assertRaisesRegex(ValueError, "投影 CRS"):
                plan_slope_from_dem({**base, "output_path": str(Path(directory) / "new.tif"), "horizontal_unit": "degrees"})
            with self.assertRaisesRegex(ValueError, "高程单位"):
                plan_slope_from_dem({**base, "output_path": str(Path(directory) / "new2.tif"), "elevation_unit": "unknown"})
            self.project.removeMapLayer(layer.id()); del layer

    def test_confirmed_slope_reopens_has_expected_angle_and_keeps_source(self):
        from qgis_copilot.tasks.processing import RasterSlopeProcessingTask
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            layer = self._dem(directory); output = Path(directory) / "slope.tif"; before_ids = set(self.project.mapLayers()); source_path = layer.source()
            plan = plan_slope_from_dem({"project": self.project, "layer_id": layer.id(), "elevation_unit": "meters", "horizontal_unit": "meters", "z_factor": 1, "output_path": str(output)})
            task = RasterSlopeProcessingTask(plan)
            received = self._wait(task)
            self.assertIsNone(received["error"], received["error"]); result = received["result"]
            self.assertTrue(output.is_file()); self.assertIn(result["output_layer_id"], self.project.mapLayers())
            self.assertEqual((result["width"], result["height"]), (3, 3)); self.assertEqual(result["crs"], "EPSG:3857")
            self.assertGreater(result["maximum"], 44.0); self.assertLess(result["maximum"], 46.0)
            self.assertEqual(layer.source(), source_path); self.assertEqual(set(self.project.mapLayers()) - before_ids, {result["output_layer_id"]})
            self.project.removeMapLayer(result["output_layer_id"])
            del task, plan, layer
            gc.collect()

    def test_confirmed_geographic_slope_reprojects_to_utm_and_writes_output(self):
        from qgis_copilot.tasks.processing import RasterSlopeProcessingTask
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            layer = self._geographic_dem(directory); output = Path(directory) / "geographic_slope.tif"
            plan = plan_slope_from_dem({"project": self.project, "layer_id": layer.id(), "elevation_unit": "meters", "horizontal_unit": "degrees", "output_path": str(output)})
            self.assertTrue(plan["parameters"]["reproject_before_slope"])
            received = self._wait(RasterSlopeProcessingTask(plan))
            self.assertIsNone(received["error"], received["error"]); result = received["result"]
            self.assertTrue(output.is_file()); self.assertTrue(result["crs"].startswith("EPSG:326"))
            self.assertGreater(result["maximum"], 0.0); self.project.removeMapLayer(result["output_layer_id"])
            self.project.removeMapLayer(layer.id()); del layer, plan
            gc.collect()


if __name__ == "__main__":
    unittest.main()
