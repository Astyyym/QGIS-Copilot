"""Validated slope plans for single-band DEM rasters."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from qgis.core import QgsRasterLayer

from .dem_parameters import build_slope_parameters, metric_crs_for_extent
from .diagnostics import _find_raster_layer
from ..qgis_tools import _project


def _output(args: dict[str, Any]) -> Path:
    raw = args.get("output_path")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("坡度分析必须明确指定新的 .tif 输出路径。")
    path = Path(raw).expanduser()
    if path.suffix.lower() not in {".tif", ".tiff"}:
        raise ValueError("坡度输出路径必须是新的 .tif 或 .tiff 文件。")
    if path.exists():
        raise ValueError("输出文件已存在；为防止覆盖，必须改用新的输出路径。")
    return path


def plan_slope_from_dem(args: dict[str, Any]) -> dict[str, Any]:
    project = _project(args)
    layer = _find_raster_layer(project, args.get("layer_id"), args.get("name"))
    if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
        raise ValueError("坡度分析要求有效的 DEM 栅格图层。")
    if layer.bandCount() != 1:
        raise ValueError("坡度分析要求单波段 DEM；请明确选择单波段输入。")
    crs = layer.crs()
    if not crs.isValid() or not crs.authid():
        raise ValueError("坡度分析要求 DEM 具有有效 CRS。")
    geographic = crs.isGeographic()
    if geographic and args.get("horizontal_unit") != "degrees":
        raise ValueError("地理 CRS 的水平单位必须明确为 degrees。")
    if not geographic and args.get("horizontal_unit") == "degrees":
        raise ValueError("投影 CRS 的水平单位不能填写 degrees。")
    params = build_slope_parameters(args, source_crs=crs.authid())
    output = _output(args)
    name = args.get("output_layer_name") or f"{layer.name()}_slope"
    if not isinstance(name, str) or not name.strip():
        raise ValueError("输出图层名称不能为空。")
    extent = layer.extent()
    metric_crs = metric_crs_for_extent(extent) if geographic else crs.authid()
    source_metadata = {"layer_id": layer.id(), "layer_name": layer.name(), "crs": crs.authid(), "width": layer.width(), "height": layer.height(), "extent": {"xmin": extent.xMinimum(), "ymin": extent.yMinimum(), "xmax": extent.xMaximum(), "ymax": extent.yMaximum()}}
    data = {"tool": "slope_from_dem", "title": "从 DEM 创建坡度栅格", "inputs": {"layer_id": layer.id(), "layer_name": layer.name(), "band": 1, "crs": crs.authid(), "width": layer.width(), "height": layer.height()}, "parameters": {**params, "algorithm": "gdal:slope", "metric_crs": metric_crs, "reproject_before_slope": geographic}, "output_path": str(output), "output_layer_name": name.strip(), "impact": "只会创建新的坡度栅格；不会修改 DEM、源文件或自动保存项目。", "risks": [f"高程单位：{params['elevation_unit']}；水平单位：{params['horizontal_unit']}。", f"结果在米制 CRS {metric_crs} 中计算，语义为坡度角度（0–90 度）。" if geographic else f"结果在输入米制 CRS {metric_crs} 中计算，语义为坡度角度（0–90 度）。", "地理 CRS 会先临时重投影到米制 CRS，临时文件在任务结束后清理。", "确认后才启动 QGIS Processing，已有输出路径会被拒绝。"]}
    data.update({"source_layer": layer, "source_metadata": source_metadata, "expected_output_crs": metric_crs, "processing_parameters": {"INPUT": layer, "BAND": 1, "SCALE": params["scale"], "AS_PERCENT": False, "COMPUTE_EDGES": False, "ZEVENBERGEN": False, "OUTPUT": str(output)}})
    return data


def dem_plan_specs(ToolSpec, PermissionLevel):
    props = {"layer_id": {"type": "string"}, "name": {"type": "string"}, "elevation_unit": {"type": "string", "enum": ["meters", "feet"]}, "horizontal_unit": {"type": "string", "enum": ["meters", "feet", "degrees"]}, "z_factor": {"type": "number", "exclusiveMinimum": 0}, "output_path": {"type": "string"}, "output_layer_name": {"type": "string"}}
    return [ToolSpec("slope_from_dem", "生成新的 DEM 坡度栅格计划，必须明确单位和 Z factor，经用户确认后执行", PermissionLevel.WRITE, plan_slope_from_dem, {"type": "object", "properties": props, "required": ["elevation_unit", "horizontal_unit", "output_path"], "additionalProperties": False})]
