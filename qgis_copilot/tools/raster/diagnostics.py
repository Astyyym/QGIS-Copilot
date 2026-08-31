"""Bounded, read-only metadata inspection for raster layers."""
from __future__ import annotations

import math
from typing import Any

from qgis.core import QgsProject, QgsRasterLayer

from ..qgis_tools import _find_layer

MAX_BANDS = 16
MAX_STATISTICS = 8


def _project(args: dict[str, Any]):
    return args.get("project") or QgsProject.instance()


def _positive_int(value: Any, name: str, maximum: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是整数。") from exc
    if not 1 <= result <= maximum:
        raise ValueError(f"{name} 必须在 1 到 {maximum} 之间。")
    return result


def _crs_authid(layer) -> str:
    crs = layer.crs()
    return crs.authid() if crs.isValid() else ""


def _find_raster_layer(project, layer_id: str | None, name: str | None):
    """Resolve the opaque ID first, then tolerate a unique visible name in it."""
    try:
        layer = _find_layer(project, layer_id, name)
    except ValueError:
        if layer_id and not name:
            matches = [item for item in project.mapLayers().values() if item.name() == layer_id]
            if len(matches) == 1:
                return matches[0]
        raise
    return layer


def _band_metadata(provider, band: int) -> dict[str, Any]:
    no_data = provider.sourceNoDataValue(band)
    has_no_data = bool(provider.useSourceNoDataValue(band))
    stats = provider.bandStatistics(band)
    finite = all(math.isfinite(float(value)) for value in (stats.minimumValue, stats.maximumValue, stats.mean, stats.stdDev))
    result: dict[str, Any] = {
        "band": band,
        "data_type": str(provider.dataType(band)),
        "no_data": no_data if has_no_data else None,
        "no_data_defined": has_no_data,
        "statistics": {"minimum": stats.minimumValue, "maximum": stats.maximumValue, "mean": stats.mean, "stddev": stats.stdDev} if finite else None,
    }
    if not has_no_data:
        result["no_data_status"] = "unknown"
    return result


def inspect_raster(args: dict[str, Any]) -> dict[str, Any]:
    """Return bounded raster metadata without writing or changing QGIS state."""
    layer = _find_raster_layer(_project(args), args.get("layer_id"), args.get("name"))
    if not isinstance(layer, QgsRasterLayer):
        raise ValueError("栅格诊断要求指定栅格图层。")
    if not layer.isValid():
        raise ValueError("栅格图层无效或 provider 无法读取。")
    provider = layer.dataProvider()
    if provider is None or not provider.isValid():
        raise ValueError("栅格 provider 不可用。")
    band_count = int(layer.bandCount())
    requested_band = args.get("band")
    if requested_band is None:
        bands = list(range(1, min(band_count, MAX_BANDS) + 1))
    else:
        bands = [_positive_int(requested_band, "band", band_count)]
    crs = _crs_authid(layer)
    if not crs:
        raise ValueError("栅格 CRS 缺失或无效。")
    extent = layer.extent()
    pixel_size = {"x": float(layer.rasterUnitsPerPixelX()), "y": float(layer.rasterUnitsPerPixelY())}
    return {
        "layer_id": layer.id(), "layer_name": layer.name(), "valid": True,
        "provider": layer.providerType(), "provider_available": True, "crs": crs,
        "extent": {"xmin": extent.xMinimum(), "ymin": extent.yMinimum(), "xmax": extent.xMaximum(), "ymax": extent.yMaximum()},
        "width": int(layer.width()), "height": int(layer.height()), "pixel_size": pixel_size,
        "band_count": band_count, "bands_returned": len(bands), "bands_truncated": band_count > len(bands),
        "bands": [_band_metadata(provider, band) for band in bands],
        "side_effects": {"project_changed": False, "layer_changed": False, "selection_changed": False, "files_created": False},
    }


def _schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "additionalProperties": False}


def raster_diagnostic_specs(ToolSpec, PermissionLevel):
    target = {"layer_id": {"type": "string"}, "name": {"type": "string"}, "band": {"type": "integer", "minimum": 1, "maximum": MAX_BANDS}}
    return [ToolSpec("inspect_raster", "读取指定栅格的有限元数据、波段、NoData和统计摘要，不修改项目", PermissionLevel.READ_ONLY, inspect_raster, _schema(target))]
