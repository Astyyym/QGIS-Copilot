"""Bounded, read-only project, layer and expression diagnostics."""
from __future__ import annotations

import math
from statistics import mean
from typing import Any

from qgis.core import QgsExpression, QgsFeatureRequest, QgsProject, QgsRasterLayer, QgsVectorLayer

from .qgis_tools import _find_layer, _project

MAX_SAMPLE = 20
MAX_SCAN = 10000


def _limit(value, default=MAX_SAMPLE, maximum=MAX_SAMPLE):
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("数量参数必须是整数。") from exc
    if not 1 <= value <= maximum:
        raise ValueError(f"数量必须在 1 到 {maximum} 之间。")
    return value


def _crs(layer):
    crs = layer.crs() if hasattr(layer, "crs") else None
    return crs.authid() if crs and crs.isValid() else ""


def get_project_diagnostics(args: dict[str, Any]) -> dict[str, Any]:
    project = _project(args)
    layers = list(project.mapLayers().values())
    invalid = [{"id": layer.id(), "name": layer.name()} for layer in layers if not layer.isValid()]
    empty = []
    editing = []
    missing_crs = []
    for layer in layers:
        if hasattr(layer, "featureCount") and layer.featureCount() == 0:
            empty.append({"id": layer.id(), "name": layer.name()})
        if hasattr(layer, "isEditable") and layer.isEditable():
            editing.append({"id": layer.id(), "name": layer.name()})
        if not _crs(layer):
            missing_crs.append({"id": layer.id(), "name": layer.name()})
    crs_values = sorted({_crs(layer) for layer in layers if _crs(layer)})
    risks = []
    if not project.fileName():
        risks.append("项目尚未保存；后续写入必须明确指定新的输出路径。")
    if project.isDirty():
        risks.append("项目有未保存修改；本诊断不会自动保存项目。")
    if editing:
        risks.append("存在活动编辑图层；进行空间处理前应提交或取消编辑。")
    if missing_crs:
        risks.append("存在未定义 CRS 的图层，空间分析距离和叠加关系可能不可靠。")
    if len(crs_values) > 1:
        risks.append("项目图层 CRS 不一致，空间分析前应明确坐标处理。")
    return {"project": {"title": project.title(), "saved": bool(project.fileName()), "dirty": project.isDirty(), "layer_count": len(layers)},
            "invalid_layers": invalid, "empty_layers": empty, "editing_layers": editing,
            "missing_crs_layers": missing_crs, "crs_values": crs_values, "risks": risks,
            "suitable_for_spatial_analysis": not (invalid or missing_crs or editing) and bool(layers)}


def check_crs_consistency(args: dict[str, Any]) -> dict[str, Any]:
    project = _project(args)
    requested = args.get("layer_ids")
    if requested is not None and (not isinstance(requested, list) or not requested):
        raise ValueError("layer_ids 必须是非空数组。")
    layers = [project.mapLayer(i) for i in requested] if requested is not None else list(project.mapLayers().values())
    if any(layer is None for layer in layers):
        raise ValueError("指定图层不存在。")
    values = [{"id": layer.id(), "name": layer.name(), "crs": _crs(layer)} for layer in layers]
    distinct = sorted({item["crs"] for item in values})
    missing = [item for item in values if not item["crs"]]
    project_crs = project.crs().authid() if project.crs().isValid() else ""
    risks = []
    if missing: risks.append("存在未定义 CRS 的图层。")
    if len(distinct) > 1: risks.append("指定图层使用多个 CRS，叠加或距离分析前需要统一坐标处理。")
    if project_crs and any(item["crs"] and item["crs"] != project_crs for item in values):
        risks.append(f"图层 CRS 与项目 CRS（{project_crs}）不完全一致。")
    return {"consistent": len(distinct) <= 1 and not missing, "project_crs": project_crs,
            "layers": values, "distinct_crs": distinct, "risks": risks,
            "recommendation": "可继续分析" if not risks else "先明确目标 CRS，再生成重投影计划。"}


def validate_layer(args: dict[str, Any]) -> dict[str, Any]:
    project = _project(args)
    layer = _find_layer(project, args.get("layer_id"), args.get("name"))
    result = {"layer_id": layer.id(), "layer_name": layer.name(), "valid": bool(layer.isValid()),
              "layer_type": "raster" if isinstance(layer, QgsRasterLayer) else "vector" if isinstance(layer, QgsVectorLayer) else "other",
              "crs": _crs(layer), "feature_count": int(layer.featureCount()) if hasattr(layer, "featureCount") else None}
    if isinstance(layer, QgsRasterLayer):
        result.update({"checks_applicable": ["validity", "crs", "dimensions"], "width": layer.width(), "height": layer.height(),
                       "vector_checks_not_applicable": ["fields", "empty_geometry", "invalid_geometry"]})
        return result
    if not isinstance(layer, QgsVectorLayer):
        raise ValueError("只支持矢量或栅格图层。")
    scan_limit = _limit(args.get("max_features", MAX_SCAN), maximum=MAX_SCAN)
    null_geometry = invalid_geometry = 0
    scanned = 0
    for feature in layer.getFeatures():
        scanned += 1
        geometry = feature.geometry()
        if geometry is None or geometry.isNull() or geometry.isEmpty(): null_geometry += 1
        elif not geometry.isGeosValid(): invalid_geometry += 1
        if scanned >= scan_limit: break
    return {**result, "fields": [field.name() for field in layer.fields()], "scanned_features": scanned,
            "scan_truncated": layer.featureCount() > scanned, "empty_geometry_count": null_geometry,
            "invalid_geometry_count": invalid_geometry, "checks_applicable": ["fields", "empty_geometry", "invalid_geometry"]}


def get_layer_statistics(args: dict[str, Any]) -> dict[str, Any]:
    layer = _find_layer(_project(args), args.get("layer_id"), args.get("name"))
    if not isinstance(layer, QgsVectorLayer): raise ValueError("字段统计只支持矢量图层。")
    field_name = args.get("field")
    if not isinstance(field_name, str) or layer.fields().indexOf(field_name) < 0: raise ValueError("字段不存在。")
    limit = _limit(args.get("max_unique", MAX_SAMPLE))
    values = [feature[field_name] for feature in layer.getFeatures()]
    non_null = [value for value in values if value is not None and value != ""]
    unique = []
    for value in non_null:
        text = str(value)
        if text not in unique:
            unique.append(text)
        if len(unique) >= limit: break
    numbers = [float(value) for value in non_null if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))]
    return {"layer_id": layer.id(), "layer_name": layer.name(), "field": field_name, "count": len(values),
            "null_count": len(values) - len(non_null), "unique_sample": unique, "unique_sample_truncated": len(set(map(str, non_null))) > len(unique),
            "numeric": {"count": len(numbers), "min": min(numbers) if numbers else None, "max": max(numbers) if numbers else None, "mean": mean(numbers) if numbers else None}}


def _expression_preview(args: dict[str, Any]) -> dict[str, Any]:
    layer = _find_layer(_project(args), args.get("layer_id"), args.get("name"))
    if not isinstance(layer, QgsVectorLayer): raise ValueError("表达式预览只支持矢量图层。")
    expression = args.get("expression")
    if not isinstance(expression, str) or not expression.strip(): raise ValueError("expression 不能为空。")
    parsed = QgsExpression(expression)
    if parsed.hasParserError(): raise ValueError(f"表达式无效：{parsed.parserErrorString()}")
    sample_limit = _limit(args.get("sample_limit", MAX_SAMPLE))
    request = QgsFeatureRequest(parsed)
    sample = []
    matched = 0
    for feature in layer.getFeatures(request):
        matched += 1
        if len(sample) < sample_limit: sample.append({field.name(): feature[field.name()] for field in layer.fields()})
    return {"layer_id": layer.id(), "layer_name": layer.name(), "expression": expression, "valid": True,
            "matched_count": matched, "sample": sample, "sample_limit": sample_limit,
            "selection_changed": False}


def validate_expression(args):
    return _expression_preview(args)


def select_by_expression_preview(args):
    return _expression_preview(args)


def selection_summary(args):
    layer = _find_layer(_project(args), args.get("layer_id"), args.get("name"))
    if not isinstance(layer, QgsVectorLayer): raise ValueError("选择集摘要只支持矢量图层。")
    limit = _limit(args.get("sample_limit", MAX_SAMPLE))
    selected_ids = layer.selectedFeatureIds()
    sample = []
    for feature_id in selected_ids[:limit]:
        feature = layer.getFeature(feature_id)
        if feature.isValid(): sample.append({field.name(): feature[field.name()] for field in layer.fields()})
    return {"layer_id": layer.id(), "layer_name": layer.name(), "selected_count": len(selected_ids), "sample": sample,
            "sample_limit": limit, "selection_changed": False}


def _schema(properties, required=None):
    value = {"type": "object", "properties": properties, "additionalProperties": False}
    if required: value["required"] = required
    return value


def diagnostic_specs(ToolSpec, PermissionLevel):
    target = {"layer_id": {"type": "string"}, "name": {"type": "string"}}
    return [
        ToolSpec("get_project_diagnostics", "检查项目是否适合空间分析，返回有限风险诊断", PermissionLevel.READ_ONLY, get_project_diagnostics, _schema({"max_layers": {"type": "integer", "minimum": 1, "maximum": 100}})),
        ToolSpec("check_crs_consistency", "检查项目或指定图层的 CRS 一致性与风险", PermissionLevel.READ_ONLY, check_crs_consistency, _schema({"layer_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 100}})),
        ToolSpec("validate_layer", "检查矢量几何/字段质量或返回栅格适用元数据", PermissionLevel.READ_ONLY, validate_layer, _schema({**target, "max_features": {"type": "integer", "minimum": 1, "maximum": MAX_SCAN}})),
        ToolSpec("get_layer_statistics", "返回指定字段的有限空值、唯一值和数值统计", PermissionLevel.READ_ONLY, get_layer_statistics, _schema({**target, "field": {"type": "string"}, "max_unique": {"type": "integer", "minimum": 1, "maximum": MAX_SAMPLE}}, ["field"])),
        ToolSpec("validate_expression", "校验表达式并预览有限命中样本，不改变选择集", PermissionLevel.READ_ONLY, validate_expression, _schema({**target, "expression": {"type": "string"}, "sample_limit": {"type": "integer", "minimum": 1, "maximum": MAX_SAMPLE}}, ["expression"])),
        ToolSpec("select_by_expression_preview", "预览表达式筛选结果，不执行选择", PermissionLevel.READ_ONLY, select_by_expression_preview, _schema({**target, "expression": {"type": "string"}, "sample_limit": {"type": "integer", "minimum": 1, "maximum": MAX_SAMPLE}}, ["expression"])),
        ToolSpec("selection_summary", "读取当前有限选择集摘要，不改变选择集", PermissionLevel.READ_ONLY, selection_summary, _schema({**target, "sample_limit": {"type": "integer", "minimum": 1, "maximum": MAX_SAMPLE}})),
    ]
