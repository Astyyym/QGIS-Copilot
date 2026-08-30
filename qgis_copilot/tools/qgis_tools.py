"""Native QGIS tools. Read tools run on QGIS's main thread; write tools first create plans."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from qgis.core import QgsProject, QgsUnitTypes, QgsVectorLayer

from qgis_copilot.context.project_context import _layer_summary, build_project_summary
from .contracts import ExecutionPlan, PermissionLevel, ToolSpec
from .registry import ToolRegistry


DEFAULT_OUTPUT_DIRECTORY_NAME = "qgis_copilot_results"


def _project(args):
    return args.get("project") or QgsProject.instance()


def _find_layer(project, layer_id: str | None, name: str | None):
    if layer_id:
        layer = project.mapLayer(layer_id)
        if layer is not None:
            return layer
    if name:
        matches = [layer for layer in project.mapLayers().values() if layer.name() == name]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError("图层名称不唯一，请改用 layer_id。")
    raise ValueError("找不到指定图层。")


def _positive_number(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是数字。") from exc
    if number <= 0:
        raise ValueError(f"{field_name} 必须大于 0。")
    return number


def _safe_output_path(project, raw_path: str | None, layer_name: str) -> Path:
    if raw_path:
        path = Path(raw_path).expanduser()
    else:
        project_path = Path(project.fileName()) if project.fileName() else None
        if project_path is None or not project_path.parent.is_dir():
            raise ValueError("当前项目尚未保存；请先保存项目或在计划中明确指定新的 .gpkg 输出路径。")
        path = project_path.parent / DEFAULT_OUTPUT_DIRECTORY_NAME / f"{layer_name}_buffer.gpkg"
    if path.suffix.lower() != ".gpkg":
        raise ValueError("输出路径必须是新的 .gpkg 文件。")
    if path.exists():
        raise ValueError("输出文件已存在；为防止覆盖，必须改用新的输出路径。")
    return path


def get_project_state(args: dict[str, Any]) -> dict[str, Any]:
    return build_project_summary(_project(args), int(args.get("max_layers", 100)))


def list_layers(args: dict[str, Any]) -> dict[str, Any]:
    summary = build_project_summary(_project(args), int(args.get("max_layers", 100)))
    return {"layers": summary["layers"], "layer_count": summary["project"]["layer_count"], "truncated": summary["truncated"]}


def inspect_layer(args: dict[str, Any]) -> dict[str, Any]:
    return {"layer": _layer_summary(_find_layer(_project(args), args.get("layer_id"), args.get("name")))}


def query_features(args: dict[str, Any]) -> dict[str, Any]:
    project = _project(args)
    layer = _find_layer(project, args.get("layer_id"), args.get("name"))
    limit = int(args.get("limit", 10))
    if limit < 1 or limit > 100:
        raise ValueError("limit 必须在 1 到 100 之间。")
    if not hasattr(layer, "fields") or not hasattr(layer, "getFeatures"):
        raise ValueError("指定图层不支持属性要素查询。")
    fields = [field.name() for field in layer.fields()]
    features = []
    iterator = layer.getFeatures()
    for feature in iterator:
        features.append({field: feature[field] for field in fields})
        if len(features) >= limit:
            break
    has_more = False
    if len(features) == limit:
        try:
            next(iterator)
            has_more = True
        except StopIteration:
            pass
    return {"layer_id": layer.id(), "layer_name": layer.name(), "fields": fields, "features": features, "returned_count": len(features), "has_more": has_more}


def plan_buffer(args: dict[str, Any]) -> dict[str, Any]:
    """Validate a non-destructive vector buffer before user confirmation."""
    project = _project(args)
    layer = _find_layer(project, args.get("layer_id"), args.get("name"))
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        raise ValueError("缓冲区输入必须是有效的矢量图层。")
    if layer.geometryType() < 0:
        raise ValueError("缓冲区输入必须具有几何对象。")
    distance = _positive_number(args.get("distance"), "distance")
    segments = int(args.get("segments", 8))
    if not 1 <= segments <= 100:
        raise ValueError("segments 必须在 1 到 100 之间。")
    output_path = _safe_output_path(project, args.get("output_path"), layer.name())
    output_layer_name = args.get("output_layer_name") or f"{layer.name()}_buffer"
    if not isinstance(output_layer_name, str) or not output_layer_name.strip():
        raise ValueError("输出图层名称不能为空。")
    crs = layer.crs()
    crs_authid = crs.authid() or "未知 CRS"
    map_units = crs.mapUnits()
    needs_metric_reprojection = map_units != QgsUnitTypes.DistanceUnit.DistanceMeters
    unit_name = QgsUnitTypes.toAbbreviatedString(map_units)
    plan = ExecutionPlan(
        tool_name="buffer_vector",
        title="创建新的矢量缓冲区",
        inputs={"layer_id": layer.id(), "layer_name": layer.name(), "crs": crs_authid, "feature_count": layer.featureCount()},
        parameters={"distance": distance, "distance_unit": "米", "segments": segments, "dissolve": bool(args.get("dissolve", False))},
        output_path=str(output_path),
        output_layer_name=output_layer_name.strip(),
        impact="只会创建一个新的 GeoPackage 图层；不会编辑原始图层、源文件或项目文件。",
        risks=(
            "缓冲距离固定按米计算。",
            f"输入 CRS 为 {crs_authid}（地图单位：{unit_name}）；" + ("执行时会临时投影到 EPSG:3857 进行米制缓冲，再转换回输入 CRS。" if needs_metric_reprojection else "可直接按米制单位执行。"),
            "输出路径已校验为不存在，确认后才会创建文件。",
        ),
    )
    plan_data = plan.as_dict()
    plan_data["source_layer"] = layer
    plan_data["source_crs"] = crs_authid
    plan_data["needs_metric_reprojection"] = needs_metric_reprojection
    plan_data["processing_parameters"] = {
        "INPUT": layer,
        "DISTANCE": distance,
        "SEGMENTS": segments,
        "END_CAP_STYLE": 0,
        "JOIN_STYLE": 0,
        "MITER_LIMIT": 2,
        "DISSOLVE": bool(args.get("dissolve", False)),
        "OUTPUT": str(output_path),
    }
    return plan_data


def _object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


def create_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    layer_target = {"layer_id": {"type": "string", "description": "QGIS 图层 ID。"}, "name": {"type": "string", "description": "唯一的图层名称；重名时请改用 layer_id。"}}
    specs = [
        ToolSpec("get_project_state", "读取当前项目的有限摘要", PermissionLevel.READ_ONLY, get_project_state, _object_schema({"max_layers": {"type": "integer", "minimum": 1, "maximum": 100}})),
        ToolSpec("list_layers", "列出当前项目图层", PermissionLevel.READ_ONLY, list_layers, _object_schema({"max_layers": {"type": "integer", "minimum": 1, "maximum": 100}})),
        ToolSpec("inspect_layer", "读取指定图层的字段、CRS和范围", PermissionLevel.READ_ONLY, inspect_layer, _object_schema(layer_target)),
        ToolSpec("query_features", "读取指定图层前 N 条属性", PermissionLevel.READ_ONLY, query_features, _object_schema({**layer_target, "limit": {"type": "integer", "minimum": 1, "maximum": 100}})),
        ToolSpec("buffer_vector", "生成新 GeoPackage 图层的矢量缓冲区计划；必须经用户确认后执行", PermissionLevel.WRITE, plan_buffer, _object_schema({**layer_target, "distance": {"type": "number", "exclusiveMinimum": 0}, "segments": {"type": "integer", "minimum": 1, "maximum": 100}, "dissolve": {"type": "boolean"}, "output_path": {"type": "string", "description": "新的 .gpkg 输出文件路径；已存在的文件会被拒绝。"}, "output_layer_name": {"type": "string"}}, ["distance"])),
    ]
    for spec in specs:
        registry.register(spec)
    return registry
