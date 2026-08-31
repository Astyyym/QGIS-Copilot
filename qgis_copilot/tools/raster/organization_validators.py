"""Content invariants for Goal 12 raster organization outputs."""
from __future__ import annotations

import math
from pathlib import Path

from qgis.core import QgsRasterLayer, QgsVectorLayer


def validate_raster_output(path: str, plan: dict) -> dict:
    output = Path(path)
    if not output.is_file():
        raise ValueError(f"Processing 已结束，但未找到输出文件：{output}")
    layer = QgsRasterLayer(str(output), plan["output_layer_name"], "gdal")
    if not layer.isValid() or layer.bandCount() < 1 or layer.width() < 1 or layer.height() < 1:
        raise ValueError("输出文件无法重新打开为有效的非空栅格。")
    if layer.crs().authid() != plan["expected_output_crs"]:
        raise ValueError("输出栅格 CRS 与计划不一致。")
    stats = layer.dataProvider().bandStatistics(1)
    if not all(math.isfinite(float(value)) for value in (stats.minimumValue, stats.maximumValue)):
        raise ValueError("输出栅格没有可验证的有限像元统计。")
    return {"layer": layer, "width": layer.width(), "height": layer.height(), "crs": layer.crs().authid(), "minimum": stats.minimumValue, "maximum": stats.maximumValue}


def validate_zonal_output(path: str, plan: dict) -> dict:
    output = Path(path)
    if not output.is_file():
        raise ValueError(f"Processing 已结束，但未找到输出文件：{output}")
    layer = QgsVectorLayer(str(output), plan["output_layer_name"], "ogr")
    if not layer.isValid() or layer.crs().authid() != plan["expected_output_crs"]:
        raise ValueError("分区统计输出无法重新打开为有效图层或 CRS 不正确。")
    expected_count = plan["inputs"]["zone_feature_count"]
    if layer.featureCount() != expected_count:
        raise ValueError("分区统计输出要素数与输入分区图层不一致。")
    names = {field.name() for field in layer.fields()}; prefix = plan["field_prefix"]
    missing = [name for name in plan["expected_statistics"] if not any(field.startswith(prefix) and name in field.lower() for field in names)]
    if missing:
        raise ValueError(f"分区统计输出缺少预期统计字段：{', '.join(missing)}")
    return {"layer": layer, "feature_count": layer.featureCount(), "crs": layer.crs().authid(), "fields": sorted(names)}