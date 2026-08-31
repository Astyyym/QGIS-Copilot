"""Result invariants for DEM slope rasters."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from qgis.core import QgsRasterLayer


def validate_slope_output(path: str, plan: dict[str, Any]) -> dict[str, Any]:
    output = Path(path)
    if not output.is_file():
        raise ValueError(f"坡度 Processing 已结束，但未找到输出文件：{output}")
    layer = QgsRasterLayer(str(output), plan["output_layer_name"], "gdal")
    if not layer.isValid():
        raise ValueError(f"输出文件存在，但 QGIS 无法重新打开坡度结果：{output}")
    if layer.bandCount() != 1:
        raise ValueError("坡度结果必须是单波段栅格。")
    source = plan["source_metadata"]
    if layer.crs().authid() != plan["expected_output_crs"]:
        raise ValueError("坡度结果 CRS 与计划的米制 CRS 不一致。")
    if layer.width() < 1 or layer.height() < 1:
        raise ValueError("坡度结果尺寸无效。")
    extent = layer.extent(); expected = source["extent"]
    if extent.isEmpty():
        raise ValueError("坡度结果范围无效。")
    provider = layer.dataProvider(); stats = provider.bandStatistics(1)
    values = (stats.minimumValue, stats.maximumValue)
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("坡度结果没有可验证的有限像元值。")
    if values[0] < -1e-6 or values[1] > 90.0001:
        raise ValueError("坡度结果超出 0 到 90 度的预期范围。")
    return {"layer": layer, "width": layer.width(), "height": layer.height(), "crs": layer.crs().authid(), "extent": {"xmin": extent.xMinimum(), "ymin": extent.yMinimum(), "xmax": extent.xMaximum(), "ymax": extent.yMaximum()}, "minimum": values[0], "maximum": values[1]}
