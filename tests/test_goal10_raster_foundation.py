"""Goal 10 raster foundation tests; run with QGIS bundled Python."""
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

from qgis_copilot.tools.contracts import PermissionLevel
from qgis_copilot.tools.qgis_tools import create_default_registry
from qgis_copilot.tools.raster.diagnostics import inspect_raster
from qgis_copilot.tools.raster.provider_probe import probe_raster_processing


class GoalTenRasterFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication([], False)
        cls.app.initQgis()

    @classmethod
    def tearDownClass(cls):
        cls.app.exitQgis()

    def setUp(self):
        self.project = QgsProject.instance()
        self.project.clear()

    def tearDown(self):
        self.project.clear()

    def _raster(self, directory: str, *, nodata: bool = True) -> QgsRasterLayer:
        path = Path(directory) / ("valid.asc" if nodata else "unknown_nodata.asc")
        header = "ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 1\n"
        if nodata:
            header += "NODATA_value -9999\n"
        path.write_text(header + "0 1\n2 3\n", encoding="ascii")
        layer = QgsRasterLayer(str(path), "tiny DEM", "gdal")
        self.assertTrue(layer.isValid(), layer.error().message())
        layer.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        self.project.addMapLayer(layer)
        return layer

    def test_valid_raster_returns_bounded_metadata_and_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            layer = self._raster(directory)
            before_layers = set(self.project.mapLayers())
            before_files = set(Path(directory).iterdir())
            result = inspect_raster({"project": self.project, "layer_id": layer.id()})
            self.assertEqual(result["provider"], "gdal")
            self.assertEqual(result["crs"], "EPSG:4326")
            self.assertEqual((result["width"], result["height"]), (2, 2))
            self.assertEqual(result["band_count"], 1)
            self.assertEqual(result["bands"][0]["no_data"], -9999.0)
            self.assertTrue(result["bands"][0]["no_data_defined"])
            self.assertLessEqual(result["bands_returned"], 16)
            self.assertFalse(result["side_effects"]["files_created"])
            self.assertEqual(set(self.project.mapLayers()), before_layers)
            self.assertEqual(set(Path(directory).iterdir()), before_files)
            self.project.removeMapLayer(layer.id())
            del layer
            gc.collect()

    def test_missing_crs_invalid_band_and_unknown_nodata_are_structured_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            layer = self._raster(directory, nodata=False)
            layer.setCrs(QgsCoordinateReferenceSystem())
            with self.assertRaisesRegex(ValueError, "CRS 缺失"):
                inspect_raster({"project": self.project, "layer_id": layer.id()})
            layer.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
            with self.assertRaisesRegex(ValueError, "band 必须在 1 到 1"):
                inspect_raster({"project": self.project, "layer_id": layer.id(), "band": 2})
            result = inspect_raster({"project": self.project, "layer_id": layer.id()})
            self.assertEqual(result["bands"][0]["no_data_status"], "unknown")
            self.assertIsNone(result["bands"][0]["no_data"])
            self.project.removeMapLayer(layer.id())
            del layer
            gc.collect()

    def test_non_raster_and_invalid_raster_are_rejected(self):
        from qgis.core import QgsVectorLayer
        vector = QgsVectorLayer("Point?crs=EPSG:4326", "points", "memory")
        self.assertTrue(vector.isValid())
        self.project.addMapLayer(vector)
        with self.assertRaisesRegex(ValueError, "栅格图层"):
            inspect_raster({"project": self.project, "layer_id": vector.id()})

    def test_visible_layer_name_in_layer_id_is_compatibly_resolved(self):
        with tempfile.TemporaryDirectory() as directory:
            layer = self._raster(directory)
            result = inspect_raster({"project": self.project, "layer_id": layer.name()})
            self.assertTrue(result["valid"])
            self.assertEqual(result["layer_name"], "tiny DEM")
            self.project.removeMapLayer(layer.id())
            del layer
            gc.collect()

    def test_provider_probe_never_exposes_writable_tools_and_reports_runtime_state(self):
        result = probe_raster_processing({})
        self.assertIn("providers", result)
        self.assertIn("algorithms", result)
        self.assertTrue(result["not_registered"])
        self.assertFalse(result["side_effects"]["processing_started"])
        names = {schema["function"]["name"]: schema for schema in create_default_registry().discover()}
        self.assertIn("inspect_raster", names)
        self.assertIn("probe_raster_processing", names)
        self.assertEqual(names["inspect_raster"]["permission"], PermissionLevel.READ_ONLY.value)
        self.assertEqual(names["probe_raster_processing"]["permission"], PermissionLevel.READ_ONLY.value)
        self.assertNotIn("gdal:slope", names)
        self.assertNotIn("gdal:aspect", names)


if __name__ == "__main__":
    unittest.main()
