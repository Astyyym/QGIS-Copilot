"""Goal 12 raster organization regression; run with QGIS bundled Python."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsProject, QgsRasterLayer, QgsVectorLayer
from qgis.PyQt.QtCore import QEventLoop, QTimer

from qgis_copilot.tools.contracts import PermissionLevel
from qgis_copilot.tools.qgis_tools import create_default_registry
from qgis_copilot.tools.raster.organization_plans import plan_clip_raster_by_mask, plan_reproject_raster, plan_zonal_statistics


class GoalTwelveRasterOrganizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication([], False); cls.app.initQgis()
        plugin_path = str(Path(cls.app.prefixPath()) / "python" / "plugins")
        if plugin_path not in sys.path: sys.path.insert(0, plugin_path)
        from processing.core.Processing import Processing
        Processing.initialize()
        cls.registry = QgsApplication.processingRegistry()
        missing = [name for name in ("gdal:cliprasterbymasklayer", "gdal:warpreproject", "native:zonalstatisticsfb") if cls.registry.algorithmById(name) is None]
        if missing: raise unittest.SkipTest(f"目标 QGIS 缺少算法：{', '.join(missing)}")

    @classmethod
    def tearDownClass(cls): cls.app.exitQgis()

    def setUp(self): self.project = QgsProject.instance(); self.project.clear()
    def tearDown(self): self.project.clear()

    def _raster(self, directory):
        path = Path(directory) / "surface.asc"
        path.write_text("ncols 4\nnrows 4\nxllcorner 0\nyllcorner 0\ncellsize 10\nNODATA_value -9999\n1 2 3 4\n5 6 7 8\n9 10 11 12\n13 14 15 16\n", encoding="ascii")
        path.with_suffix(".prj").write_text(QgsCoordinateReferenceSystem("EPSG:3857").toWkt(), encoding="ascii")
        layer = QgsRasterLayer(str(path), "surface", "gdal"); self.assertTrue(layer.isValid(), layer.error().message()); self.project.addMapLayer(layer)
        return layer

    def _zones(self):
        layer = QgsVectorLayer("Polygon?crs=EPSG:3857", "zones", "memory"); self.assertTrue(layer.isValid())
        provider = layer.dataProvider()
        for wkt in ("POLYGON((0 0,20 0,20 40,0 40,0 0))", "POLYGON((20 0,40 0,40 40,20 40,20 0))"):
            feature = QgsFeature(); feature.setGeometry(QgsGeometry.fromWkt(wkt)); provider.addFeature(feature)
        self.project.addMapLayer(layer); return layer

    def _wait(self, task):
        received = {"result": None, "error": None, "cancelled": False}; loop = QEventLoop()
        task.completed.connect(lambda value: (received.__setitem__("result", value), loop.quit()))
        task.failed.connect(lambda value: (received.__setitem__("error", value), loop.quit()))
        task.cancelled.connect(lambda: (received.__setitem__("cancelled", True), loop.quit()))
        task.start(); timer = QTimer(); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(20000); loop.exec()
        self.assertTrue(timer.isActive(), "Goal 12 Processing 超过 20 秒未结束"); timer.stop(); return received

    def test_registry_exposes_only_confirmed_write_plans(self):
        schemas = {item["function"]["name"]: item for item in create_default_registry().discover()}
        for name in ("clip_raster_by_mask", "reproject_raster", "zonal_statistics"):
            self.assertEqual(schemas[name]["permission"], PermissionLevel.WRITE.value)

    def test_plans_reject_collisions_and_do_not_change_project(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            raster = self._raster(directory); zones = self._zones(); before = set(self.project.mapLayers())
            output = Path(directory) / "exists.tif"; output.write_bytes(b"keep")
            with self.assertRaisesRegex(ValueError, "已存在"):
                plan_clip_raster_by_mask({"project": self.project, "layer_id": raster.id(), "mask_layer_id": zones.id(), "output_path": str(output)})
            with self.assertRaisesRegex(ValueError, "目标 CRS 无效"):
                plan_reproject_raster({"project": self.project, "layer_id": raster.id(), "target_crs": "not-a-crs", "output_path": str(Path(directory) / "new.tif")})
            with self.assertRaisesRegex(ValueError, "statistics"):
                plan_zonal_statistics({"project": self.project, "layer_id": raster.id(), "zone_layer_id": zones.id(), "statistics": ["bad"], "output_path": str(Path(directory) / "zones.gpkg")})
            self.assertEqual(output.read_bytes(), b"keep"); self.assertEqual(set(self.project.mapLayers()), before)

    def test_confirmed_clip_and_reproject_reopen_without_changing_source(self):
        from qgis_copilot.tasks.processing import RasterOrganizationProcessingTask
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            raster = self._raster(directory); zones = self._zones(); source = raster.source()
            clip_path = Path(directory) / "clip.tif"
            clip = plan_clip_raster_by_mask({"project": self.project, "layer_id": raster.id(), "mask_layer_id": zones.id(), "output_path": str(clip_path)})
            self.assertFalse(clip_path.exists()); clipped = self._wait(RasterOrganizationProcessingTask(clip))
            self.assertIsNone(clipped["error"], clipped["error"]); self.assertTrue(clip_path.is_file()); self.assertIn(clipped["result"]["output_layer_id"], self.project.mapLayers())
            reproj_path = Path(directory) / "reproject.tif"
            reproj = plan_reproject_raster({"project": self.project, "layer_id": raster.id(), "target_crs": "EPSG:4326", "resampling": "bilinear", "resolution": 0.0001, "output_path": str(reproj_path)})
            reprojected = self._wait(RasterOrganizationProcessingTask(reproj))
            self.assertIsNone(reprojected["error"], reprojected["error"]); self.assertEqual(reprojected["result"]["crs"], "EPSG:4326")
            self.assertEqual(raster.source(), source)

    def test_confirmed_zonal_statistics_copies_zones_and_creates_fields(self):
        from qgis_copilot.tasks.processing import RasterOrganizationProcessingTask
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            raster = self._raster(directory); zones = self._zones(); source_fields = [field.name() for field in zones.fields()]
            output = Path(directory) / "zonal.gpkg"
            plan = plan_zonal_statistics({"project": self.project, "layer_id": raster.id(), "zone_layer_id": zones.id(), "band": 1, "statistics": ["count", "mean", "min", "max"], "field_prefix": "zs_", "output_path": str(output)})
            self.assertFalse(output.exists()); received = self._wait(RasterOrganizationProcessingTask(plan))
            self.assertIsNone(received["error"], received["error"]); result = received["result"]
            self.assertTrue(output.is_file()); self.assertEqual(result["feature_count"], 2); self.assertIn(result["output_layer_id"], self.project.mapLayers())
            self.assertEqual([field.name() for field in zones.fields()], source_fields)


if __name__ == "__main__": unittest.main()