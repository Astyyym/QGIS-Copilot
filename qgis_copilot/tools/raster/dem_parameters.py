"""Explicit unit and GDAL slope parameter semantics."""
from __future__ import annotations

from typing import Any

from qgis.core import QgsCoordinateReferenceSystem

ELEVATION_UNITS_TO_METERS = {"meters": 1.0, "metres": 1.0, "m": 1.0, "feet": 0.3048, "ft": 0.3048}
HORIZONTAL_UNITS_TO_METERS = {**ELEVATION_UNITS_TO_METERS, "degrees": 111320.0, "degree": 111320.0}


def _unit(value: Any, name: str, table: dict[str, float]) -> tuple[str, float]:
    if not isinstance(value, str) or value.strip().lower() not in table:
        raise ValueError(f"{name} 必须明确为 meters、feet 或 degrees。")
    key = value.strip().lower()
    return key, table[key]


def build_slope_parameters(args: dict[str, Any], *, source_crs: str) -> dict[str, Any]:
    """Validate explicit units and return stable GDAL slope parameters."""
    elevation_unit, elevation_m = _unit(args.get("elevation_unit"), "高程单位", ELEVATION_UNITS_TO_METERS)
    horizontal_unit, horizontal_m = _unit(args.get("horizontal_unit"), "水平单位", HORIZONTAL_UNITS_TO_METERS)

    try:
        z_factor = float(args.get("z_factor", 1.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Z factor 必须是数字。") from exc
    if z_factor <= 0 or z_factor > 100000:
        raise ValueError("Z factor 必须大于 0 且不超过 100000。")
    # Geographic input is warped to meters before slope, so degrees do not
    # participate in the GDAL scale after the reprojection stage.
    scale = z_factor * elevation_m / (1.0 if horizontal_unit == "degrees" else horizontal_m)
    return {
        "algorithm": "gdal:slope",
        "source_crs": source_crs,
        "elevation_unit": elevation_unit,
        "horizontal_unit": horizontal_unit,
        "z_factor": z_factor,
        "scale": scale,
        "as_percent": False,
        "compute_edges": False,
        "zevenbergen": False,
    }


def metric_crs_for_extent(extent) -> str:
    """Choose the UTM zone containing the raster center for geographic input."""
    center = extent.center()
    zone = int((center.x() + 180.0) // 6.0) + 1
    zone = max(1, min(60, zone))
    epsg = (32600 if center.y() >= 0 else 32700) + zone
    crs = QgsCoordinateReferenceSystem(f"EPSG:{epsg}")
    if not crs.isValid():
        raise ValueError("无法为地理 CRS 选择有效的米制投影 CRS。")
    return crs.authid()
