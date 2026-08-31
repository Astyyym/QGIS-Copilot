"""Validated, non-overwriting raster organization and zonal-statistics plans."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from qgis.core import QgsCoordinateReferenceSystem, QgsRasterLayer, QgsVectorLayer

from ..contracts import ExecutionPlan, PermissionLevel, ToolSpec
from ..qgis_tools import _project
from .diagnostics import _find_raster_layer


_RESAMPLING = {"nearest": 0, "bilinear": 1, "cubic": 2, "cubicspline": 3, "lanczos": 4}
_STATISTICS = {"count": 0, "sum": 1, "mean": 2, "median": 3, "stdev": 4, "min": 5, "max": 6, "range": 7, "minority": 8, "majority": 9, "variety": 10, "variance": 11}


def _new_tiff(raw_path: Any, label: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError(f"{label}必须明确指定新的 .tif 输出路径。")
    path = Path(raw_path).expanduser()
    if path.suffix.lower() not in {".tif", ".tiff"}:
        raise ValueError(f"{label}输出路径必须是新的 .tif 或 .tiff 文件。")
    if path.exists():
        raise ValueError("输出文件已存在；为防止覆盖，必须改用新的输出路径。")
    return path


def _new_gpkg(raw_path: Any) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("分区统计必须明确指定新的 .gpkg 输出路径。")
    path = Path(raw_path).expanduser()
    if path.suffix.lower() != ".gpkg":
        raise ValueError("分区统计输出路径必须是新的 .gpkg 文件。")
    if path.exists():
        raise ValueError("输出文件已存在；为防止覆盖，必须改用新的输出路径。")
    return path


def _output_name(raw_name: Any, fallback: str) -> str:
    name = raw_name or fallback
    if not isinstance(name, str) or not name.strip():
        raise ValueError("输出图层名称不能为空。")
    return name.strip()


def _valid_raster(project, args: dict[str, Any], label: str) -> QgsRasterLayer:
    layer = _find_raster_layer(project, args.get("layer_id"), args.get("name"))
    if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
        raise ValueError(f"{label}要求有效栅格图层。")
    if not layer.crs().isValid() or not layer.crs().authid():
        raise ValueError(f"{label}要求栅格具有有效 CRS。")
    return layer


def _band(layer: QgsRasterLayer, value: Any) -> int:
    try:
        band = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("band 必须是整数。") from exc
    if not 1 <= band <= layer.bandCount():
        raise ValueError(f"band 必须在 1 到 {layer.bandCount()} 之间。")
    return band


def plan_clip_raster_by_mask(args: dict[str, Any]) -> dict[str, Any]:
    project = _project(args); raster = _valid_raster(project, args, "栅格裁剪")
    mask = project.mapLayer(args.get("mask_layer_id")) if args.get("mask_layer_id") else None
    if mask is None and args.get("mask_name"):
        matches = [item for item in project.mapLayers().values() if item.name() == args["mask_name"]]
        if len(matches) == 1: mask = matches[0]
        elif len(matches) > 1: raise ValueError("掩膜图层名称不唯一，请改用 mask_layer_id。")
    if not isinstance(mask, QgsVectorLayer) or not mask.isValid() or mask.geometryType() != 2:
        raise ValueError("栅格裁剪要求有效的面矢量掩膜图层。")
    if not mask.crs().isValid() or mask.crs() != raster.crs():
        raise ValueError("栅格裁剪要求栅格与面掩膜具有一致的有效 CRS。")
    output = _new_tiff(args.get("output_path"), "栅格裁剪")
    plan = ExecutionPlan("clip_raster_by_mask", "按面掩膜裁剪新的栅格",
        {"layer_id": raster.id(), "layer_name": raster.name(), "band_count": raster.bandCount(), "crs": raster.crs().authid(), "mask_layer_id": mask.id(), "mask_layer_name": mask.name(), "mask_feature_count": mask.featureCount()},
        {"algorithm": "gdal:cliprasterbymasklayer", "crop_to_mask": True, "keep_resolution": True}, str(output), _output_name(args.get("output_layer_name"), f"{raster.name()}_clip"),
        "只会创建新的裁剪栅格；不会修改输入栅格、掩膜图层、源文件或自动保存项目。",
        ("输入栅格与面掩膜 CRS 已校验一致。", "裁剪范围和 NoData 边缘将由 GDAL 根据掩膜生成。", "确认后才启动 Processing；已存在输出会被拒绝。"))
    data = plan.as_dict(); data.update({"source_layer": raster, "mask_layer": mask, "expected_output_crs": raster.crs().authid(), "processing_parameters": {"INPUT": raster, "MASK": mask, "SOURCE_CRS": None, "TARGET_CRS": None, "NODATA": None, "ALPHA_BAND": False, "CROP_TO_CUTLINE": True, "KEEP_RESOLUTION": True, "SET_RESOLUTION": False, "X_RESOLUTION": None, "Y_RESOLUTION": None, "MULTITHREADING": False, "OPTIONS": "", "DATA_TYPE": 0, "EXTRA": "", "OUTPUT": str(output)}})
    return data


def plan_reproject_raster(args: dict[str, Any]) -> dict[str, Any]:
    project = _project(args); raster = _valid_raster(project, args, "栅格重投影")
    target = QgsCoordinateReferenceSystem(str(args.get("target_crs") or ""))
    if not target.isValid() or not target.authid():
        raise ValueError("目标 CRS 无效；请使用明确的 EPSG 或完整 CRS 定义。")
    method = args.get("resampling", "nearest")
    if method not in _RESAMPLING:
        raise ValueError("resampling 仅支持 nearest、bilinear、cubic、cubicspline 或 lanczos。")
    resolution = args.get("resolution")
    if resolution is not None:
        try: resolution = float(resolution)
        except (TypeError, ValueError) as exc: raise ValueError("resolution 必须是正数。") from exc
        if resolution <= 0: raise ValueError("resolution 必须是正数。")
    output = _new_tiff(args.get("output_path"), "栅格重投影")
    target_crs = target.authid()
    plan = ExecutionPlan("reproject_raster", "创建新的重投影栅格",
        {"layer_id": raster.id(), "layer_name": raster.name(), "band_count": raster.bandCount(), "source_crs": raster.crs().authid(), "width": raster.width(), "height": raster.height()},
        {"algorithm": "gdal:warpreproject", "target_crs": target_crs, "resampling": method, "resolution": resolution}, str(output), _output_name(args.get("output_layer_name"), f"{raster.name()}_{target_crs.replace(':', '_')}"),
        "只会创建新的重投影栅格；不会覆盖输入栅格、源文件或自动保存项目。",
        (f"将从 {raster.crs().authid()} 转换到 {target_crs}。", f"重采样方法：{method}。", "分辨率已明确记录；未指定时由 GDAL 根据转换结果确定。", "确认后才启动 Processing；已存在输出会被拒绝。"))
    params = {"INPUT": raster, "SOURCE_CRS": raster.crs().authid(), "TARGET_CRS": target_crs, "RESAMPLING": _RESAMPLING[method], "NODATA": None, "TARGET_RESOLUTION": resolution, "OPTIONS": "", "DATA_TYPE": 0, "TARGET_EXTENT": None, "TARGET_EXTENT_CRS": None, "MULTITHREADING": False, "EXTRA": "", "OUTPUT": str(output)}
    data = plan.as_dict(); data.update({"source_layer": raster, "expected_output_crs": target_crs, "processing_parameters": params})
    return data


def plan_zonal_statistics(args: dict[str, Any]) -> dict[str, Any]:
    project = _project(args); raster = _valid_raster(project, args, "分区统计"); band = _band(raster, args.get("band", 1))
    zones = project.mapLayer(args.get("zone_layer_id")) if args.get("zone_layer_id") else None
    if zones is None and args.get("zone_name"):
        matches = [item for item in project.mapLayers().values() if item.name() == args["zone_name"]]
        if len(matches) == 1: zones = matches[0]
        elif len(matches) > 1: raise ValueError("分区图层名称不唯一，请改用 zone_layer_id。")
    if not isinstance(zones, QgsVectorLayer) or not zones.isValid() or zones.geometryType() != 2:
        raise ValueError("分区统计要求有效的面矢量分区图层。")
    if not zones.crs().isValid() or zones.crs() != raster.crs():
        raise ValueError("分区统计要求栅格与分区图层具有一致的有效 CRS。")
    requested = args.get("statistics", ["count", "mean", "min", "max"])
    if not isinstance(requested, list) or not requested or any(item not in _STATISTICS for item in requested):
        raise ValueError("statistics 必须是支持项的非空列表：count、sum、mean、median、stdev、min、max、range、minority、majority、variety、variance。")
    statistics = list(dict.fromkeys(requested)); prefix = args.get("field_prefix", "zs_")
    if not isinstance(prefix, str) or not prefix or len(prefix) > 20 or not prefix.replace("_", "").isalnum():
        raise ValueError("field_prefix 必须是 1–20 个字母、数字或下划线，且不能为空。")
    output = _new_gpkg(args.get("output_path")); name = _output_name(args.get("output_layer_name"), f"{zones.name()}_zonal")
    plan = ExecutionPlan("zonal_statistics", "生成包含栅格分区统计的新面图层",
        {"zone_layer_id": zones.id(), "zone_layer_name": zones.name(), "zone_feature_count": zones.featureCount(), "raster_layer_id": raster.id(), "raster_layer_name": raster.name(), "band": band, "crs": raster.crs().authid()},
        {"algorithm": "native:zonalstatisticsfb", "band": band, "statistics": statistics, "field_prefix": prefix}, str(output), name,
        "只会创建包含统计字段的新 GeoPackage 面图层；不会把字段写回分区图层，不会修改栅格、源文件或自动保存项目。",
        ("统计波段、统计项和字段前缀已明确。", "分区图层会复制到新输出，原图层不会被原地写入。", "已存在输出会被拒绝，确认后才启动 Processing。"))
    params = {"INPUT": zones, "INPUT_RASTER": raster, "RASTER_BAND": band, "COLUMN_PREFIX": prefix, "STATISTICS": [_STATISTICS[item] for item in statistics], "OUTPUT": str(output)}
    data = plan.as_dict(); data.update({"source_layer": zones, "raster_layer": raster, "expected_output_crs": zones.crs().authid(), "expected_statistics": statistics, "field_prefix": prefix, "processing_parameters": params})
    return data


def raster_organization_specs():
    raster_target = {"layer_id": {"type": "string"}, "name": {"type": "string"}}
    output = {"output_path": {"type": "string"}, "output_layer_name": {"type": "string"}}
    clip = {"type": "object", "properties": {**raster_target, "mask_layer_id": {"type": "string"}, "mask_name": {"type": "string"}, **output}, "required": ["output_path"], "additionalProperties": False}
    reproj = {"type": "object", "properties": {**raster_target, "target_crs": {"type": "string"}, "resampling": {"type": "string", "enum": list(_RESAMPLING)}, "resolution": {"type": "number", "exclusiveMinimum": 0}, **output}, "required": ["target_crs", "output_path"], "additionalProperties": False}
    zonal = {"type": "object", "properties": {**raster_target, "zone_layer_id": {"type": "string"}, "zone_name": {"type": "string"}, "band": {"type": "integer", "minimum": 1}, "statistics": {"type": "array", "items": {"type": "string", "enum": list(_STATISTICS)}}, "field_prefix": {"type": "string"}, **output}, "required": ["output_path"], "additionalProperties": False}
    return [ToolSpec("clip_raster_by_mask", "按面掩膜生成新的裁剪栅格计划，必须经用户确认后执行", PermissionLevel.WRITE, plan_clip_raster_by_mask, clip), ToolSpec("reproject_raster", "生成新的栅格重投影计划，必须明确目标 CRS、重采样和输出路径", PermissionLevel.WRITE, plan_reproject_raster, reproj), ToolSpec("zonal_statistics", "生成包含明确栅格分区统计的新面图层计划，不原地写回输入", PermissionLevel.WRITE, plan_zonal_statistics, zonal)]