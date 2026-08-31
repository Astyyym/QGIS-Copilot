"""Validated, non-overwriting vector Processing plans."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from qgis.core import QgsCoordinateReferenceSystem, QgsExpression, QgsFeatureRequest, QgsVectorLayer

from .qgis_tools import _find_layer, _project
from .contracts import ExecutionPlan, PermissionLevel, ToolSpec


def _output_path(project, raw_path, layer_name):
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("重投影必须明确指定新的 .gpkg 输出路径。")
    path = Path(raw_path).expanduser()
    if path.suffix.lower() != ".gpkg":
        raise ValueError("输出路径必须是新的 .gpkg 文件。")
    if path.exists():
        raise ValueError("输出文件已存在；为防止覆盖，必须改用新的输出路径。")
    return path


def _vector_layer(project, layer_id, name, label):
    layer = _find_layer(project, layer_id, name)
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid() or layer.geometryType() < 0:
        raise ValueError(f"{label}必须是具有几何对象的有效矢量图层。")
    return layer


def _output_name(raw_name, fallback):
    name = raw_name or fallback
    if not isinstance(name, str) or not name.strip():
        raise ValueError("输出图层名称不能为空。")
    return name.strip()


def _field_names(layer, raw_fields, label):
    available = [field.name() for field in layer.fields()]
    if raw_fields is None:
        return available
    if not isinstance(raw_fields, list) or not raw_fields:
        raise ValueError(f"{label}字段必须是非空字段名列表，或省略以保留全部字段。")
    if any(not isinstance(name, str) or not name.strip() for name in raw_fields):
        raise ValueError(f"{label}字段名必须是非空字符串。")
    names = [name.strip() for name in raw_fields]
    if len(set(names)) != len(names) or any(name not in available for name in names):
        raise ValueError(f"{label}字段列表包含重复或不存在的字段。")
    return names


def plan_intersection(args: dict[str, Any]) -> dict[str, Any]:
    project = _project(args)
    input_layer = _vector_layer(project, args.get("input_layer_id"), args.get("input_name"), "相交输入")
    overlay_layer = _vector_layer(project, args.get("overlay_layer_id"), args.get("overlay_name"), "相交叠加")
    _same_crs(input_layer, overlay_layer, "相交")
    input_fields = _field_names(input_layer, args.get("input_fields"), "输入")
    overlay_fields = _field_names(overlay_layer, args.get("overlay_fields"), "叠加")
    collisions = sorted(set(input_fields) & set(overlay_fields))
    prefix = args.get("overlay_prefix", "overlay_")
    if collisions and (not isinstance(prefix, str) or not prefix.strip()):
        raise ValueError(f"相交存在同名字段 {', '.join(collisions)}；必须明确非空 overlay_prefix。")
    prefix = prefix.strip()
    output = _output_path(project, args.get("output_path"), input_layer.name())
    name = _output_name(args.get("output_layer_name"), f"{input_layer.name()}_intersection")
    plan = ExecutionPlan(
        "intersection", "创建新的矢量相交图层",
        {"input_layer_id": input_layer.id(), "input_layer_name": input_layer.name(), "overlay_layer_id": overlay_layer.id(),
         "overlay_layer_name": overlay_layer.name(), "input_feature_count": input_layer.featureCount(),
         "overlay_feature_count": overlay_layer.featureCount(), "crs": input_layer.crs().authid()},
        {"algorithm": "native:intersection", "input_fields": input_fields, "overlay_fields": overlay_fields,
         "overlay_prefix": prefix, "field_conflicts": collisions}, str(output), name,
        "只会创建新的 GeoPackage 结果；不会修改两个输入图层、源文件或自动保存项目。",
        ("输入与叠加图层 CRS 已校验一致。", "无相交时结果可能为零要素。", "同名叠加字段将使用明确前缀。", "已存在输出路径会被拒绝。"))
    data = plan.as_dict(); data.update({"source_layer": input_layer, "overlay_layer": overlay_layer,
        "processing_parameters": {"INPUT": input_layer, "OVERLAY": overlay_layer, "INPUT_FIELDS": input_fields,
                                   "OVERLAY_FIELDS": overlay_fields, "PREFIX": prefix, "OUTPUT": str(output)}})
    return data


def plan_dissolve(args: dict[str, Any]) -> dict[str, Any]:
    project = _project(args)
    layer = _vector_layer(project, args.get("layer_id"), args.get("name"), "融合输入")
    field = args.get("dissolve_field")
    dissolve_all = bool(args.get("dissolve_all", False))
    if bool(field) == dissolve_all:
        raise ValueError("融合必须明确提供 dissolve_field，或将 dissolve_all 设为 true，不能由插件猜测。")
    if field is not None:
        if not isinstance(field, str) or field not in [item.name() for item in layer.fields()]:
            raise ValueError("dissolve_field 必须是输入图层中存在的字段。")
        fields = [field]
    else:
        fields = []
    output = _output_path(project, args.get("output_path"), layer.name())
    name = _output_name(args.get("output_layer_name"), f"{layer.name()}_dissolve")
    plan = ExecutionPlan(
        "dissolve", "创建新的矢量融合图层",
        {"layer_id": layer.id(), "layer_name": layer.name(), "feature_count": layer.featureCount(), "crs": layer.crs().authid()},
        {"algorithm": "native:dissolve", "dissolve_field": field, "dissolve_all": dissolve_all}, str(output), name,
        "只会创建新的 GeoPackage 结果；不会修改输入图层、源文件或自动保存项目。",
        ("融合规则已明确，不会自动选择分类字段。", "融合可能改变几何数量和边界形状。", "已存在输出路径会被拒绝。"))
    data = plan.as_dict(); data.update({"source_layer": layer,
        "processing_parameters": {"INPUT": layer, "FIELD": fields, "OUTPUT": str(output)}})
    return data


def _same_crs(first, second, operation):
    if not first.crs().isValid() or not second.crs().isValid():
        raise ValueError(f"{operation}要求输入图层具有有效 CRS。")
    if first.crs() != second.crs():
        raise ValueError(f"{operation}要求输入图层 CRS 一致；请先明确坐标处理或生成重投影计划。")


def plan_reproject(args: dict[str, Any]) -> dict[str, Any]:
    project = _project(args)
    layer = _vector_layer(project, args.get("layer_id"), args.get("name"), "重投影输入")
    target_raw = args.get("target_crs")
    target = QgsCoordinateReferenceSystem(str(target_raw or ""))
    if not target.isValid():
        raise ValueError("目标 CRS 无效；请使用明确的 EPSG 或完整 CRS 定义。")
    source = layer.crs().authid() or "未知 CRS"
    target_authid = target.authid() or str(target_raw)
    if not target_authid:
        raise ValueError("目标 CRS 必须可识别。")
    output = _output_path(project, args.get("output_path"), layer.name())
    name = _output_name(args.get("output_layer_name"), f"{layer.name()}_{target_authid.replace(':', '_')}")
    plan = ExecutionPlan(
        tool_name="reproject_layer", title="创建新的重投影图层",
        inputs={"layer_id": layer.id(), "layer_name": layer.name(), "source_crs": source, "feature_count": layer.featureCount()},
        parameters={"target_crs": target_authid}, output_path=str(output), output_layer_name=name,
        impact="只会创建一个新的 GeoPackage 图层；不会覆盖源图层、源文件或自动保存项目。",
        risks=("目标 CRS 必须由用户明确指定，插件不会猜测。", f"将从 {source} 转换到 {target_authid}。", "确认后才会创建输出文件，已存在路径会被拒绝。"),
    )
    data = plan.as_dict()
    data.update({"source_layer": layer, "source_crs": source, "target_crs": target_authid,
                 "processing_parameters": {"INPUT": layer, "TARGET_CRS": target_authid, "OUTPUT": str(output)}})
    return data


def plan_clip_vector(args: dict[str, Any]) -> dict[str, Any]:
    project = _project(args)
    input_layer = _vector_layer(project, args.get("input_layer_id"), args.get("input_name"), "裁剪输入")
    mask_layer = _vector_layer(project, args.get("mask_layer_id"), args.get("mask_name"), "裁剪掩膜")
    if mask_layer.geometryType() != 2:
        raise ValueError("裁剪掩膜必须是面图层。")
    _same_crs(input_layer, mask_layer, "裁剪")
    output = _output_path(project, args.get("output_path"), input_layer.name())
    name = _output_name(args.get("output_layer_name"), f"{input_layer.name()}_clip")
    plan = ExecutionPlan("clip_vector", "创建新的矢量裁剪图层",
        {"layer_id": input_layer.id(), "layer_name": input_layer.name(), "feature_count": input_layer.featureCount(),
         "mask_layer_id": mask_layer.id(), "mask_layer_name": mask_layer.name(), "mask_feature_count": mask_layer.featureCount(), "crs": input_layer.crs().authid()},
        {"algorithm": "native:clip"}, str(output), name,
        "只会创建新的 GeoPackage 结果；不会修改输入图层、掩膜图层、源文件或自动保存项目。",
        ("输入与掩膜 CRS 已校验一致。", "无交集时可能生成零要素结果。", "已存在输出路径会被拒绝，确认后才创建文件。"))
    data = plan.as_dict(); data.update({"source_layer": input_layer, "mask_layer": mask_layer,
        "processing_parameters": {"INPUT": input_layer, "OVERLAY": mask_layer, "OUTPUT": str(output)}})
    return data


def _validated_expression(layer, expression):
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("筛选导出必须提供已验证的 expression 或明确的选择集摘要。")
    parsed = QgsExpression(expression)
    if parsed.hasParserError():
        raise ValueError(f"表达式无效：{parsed.parserErrorString()}")
    count = sum(1 for _ in layer.getFeatures(QgsFeatureRequest(parsed)))
    return expression, count


def plan_export_filtered_features(args: dict[str, Any]) -> dict[str, Any]:
    project = _project(args)
    layer = _vector_layer(project, args.get("layer_id"), args.get("name"), "筛选导出输入")
    filter_kind = args.get("filter_kind")
    if filter_kind == "expression":
        expression, count = _validated_expression(layer, args.get("expression"))
        parameters = {"filter_kind": "expression", "expression": expression}
    elif filter_kind == "selection":
        selected_ids = sorted(layer.selectedFeatureIds())
        if not selected_ids:
            raise ValueError("当前选择集为空；无法导出。")
        expected_ids = args.get("selected_feature_ids")
        if not isinstance(expected_ids, list) or sorted(expected_ids) != selected_ids:
            raise ValueError("选择集已变化或未提供已验证的 selected_feature_ids；请先重新读取选择集摘要。")
        count, parameters = len(selected_ids), {"filter_kind": "selection", "selected_feature_ids": selected_ids}
    elif filter_kind == "spatial_preview":
        ids = args.get("matched_feature_ids")
        if not isinstance(ids, list) or not ids:
            raise ValueError("空间条件必须提供已验证且非空的 matched_feature_ids。")
        existing = {feature.id() for feature in layer.getFeatures()}
        if any(not isinstance(value, int) or value not in existing for value in ids):
            raise ValueError("空间预览结果已失效；请重新运行空间关系预览。")
        count, parameters = len(ids), {"filter_kind": "spatial_preview", "matched_feature_ids": sorted(set(ids))}
    else:
        raise ValueError("filter_kind 仅支持 expression、selection 或 spatial_preview。")
    if count == 0:
        raise ValueError("筛选条件没有匹配要素；不会创建空输出。")
    output = _output_path(project, args.get("output_path"), layer.name())
    name = _output_name(args.get("output_layer_name"), f"{layer.name()}_filtered")
    plan = ExecutionPlan("export_filtered_features", "导出新的筛选要素图层",
        {"layer_id": layer.id(), "layer_name": layer.name(), "feature_count": layer.featureCount(), "crs": layer.crs().authid()},
        {**parameters, "estimated_feature_count": count}, str(output), name,
        "只会导出新的 GeoPackage 图层；不会修改源图层、选择集、源文件或自动保存项目。",
        ("筛选基础已在计划阶段重新校验。", "选择集基础会在确认前再次校验，变化时拒绝执行。", "已存在输出路径会被拒绝，确认后才创建文件。"))
    data = plan.as_dict(); data.update({"source_layer": layer, "processing_parameters": {"INPUT": layer, "OUTPUT": str(output)}})
    return data


def processing_specs():
    target = {"layer_id": {"type": "string"}, "name": {"type": "string"}}
    schema = {"type": "object", "properties": {**target,
        "target_crs": {"type": "string", "description": "明确的目标 CRS，例如 EPSG:3857"},
        "output_path": {"type": "string", "description": "新的 .gpkg 路径，不覆盖已有文件"},
        "output_layer_name": {"type": "string"}}, "required": ["target_crs", "output_path"], "additionalProperties": False}
    clip_schema = {"type": "object", "properties": {"input_layer_id": {"type": "string"}, "input_name": {"type": "string"}, "mask_layer_id": {"type": "string"}, "mask_name": {"type": "string"}, "output_path": {"type": "string"}, "output_layer_name": {"type": "string"}}, "required": ["output_path"], "additionalProperties": False}
    export_schema = {"type": "object", "properties": {**target, "filter_kind": {"type": "string", "enum": ["expression", "selection", "spatial_preview"]}, "expression": {"type": "string"}, "selected_feature_ids": {"type": "array", "items": {"type": "integer"}}, "matched_feature_ids": {"type": "array", "items": {"type": "integer"}}, "output_path": {"type": "string"}, "output_layer_name": {"type": "string"}}, "required": ["filter_kind", "output_path"], "additionalProperties": False}
    intersection_schema = {"type": "object", "properties": {"input_layer_id": {"type": "string"}, "input_name": {"type": "string"}, "overlay_layer_id": {"type": "string"}, "overlay_name": {"type": "string"}, "input_fields": {"type": "array", "items": {"type": "string"}}, "overlay_fields": {"type": "array", "items": {"type": "string"}}, "overlay_prefix": {"type": "string"}, "output_path": {"type": "string"}, "output_layer_name": {"type": "string"}}, "required": ["output_path"], "additionalProperties": False}
    dissolve_schema = {"type": "object", "properties": {**target, "dissolve_field": {"type": "string"}, "dissolve_all": {"type": "boolean"}, "output_path": {"type": "string"}, "output_layer_name": {"type": "string"}}, "required": ["output_path"], "additionalProperties": False}
    return [
        ToolSpec("reproject_layer", "生成新的矢量重投影图层计划，必须经用户确认后执行", PermissionLevel.WRITE, plan_reproject, schema),
        ToolSpec("clip_vector", "生成新的矢量裁剪图层计划，必须经用户确认后执行", PermissionLevel.WRITE, plan_clip_vector, clip_schema),
        ToolSpec("export_filtered_features", "基于已验证条件导出新的筛选要素图层计划，必须经用户确认后执行", PermissionLevel.WRITE, plan_export_filtered_features, export_schema),
        ToolSpec("intersection", "生成新的矢量相交图层计划，必须经用户确认后执行", PermissionLevel.WRITE, plan_intersection, intersection_schema),
        ToolSpec("dissolve", "生成新的矢量融合图层计划，必须明确分类字段或全量融合并经用户确认后执行", PermissionLevel.WRITE, plan_dissolve, dissolve_schema),
    ]
