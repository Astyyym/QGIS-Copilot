"""Bounded, non-mutating spatial relationship previews for vector layers."""
from __future__ import annotations

from typing import Any

from qgis.core import QgsVectorLayer

from .diagnostics_tools import MAX_SAMPLE, MAX_SCAN, _limit
from .qgis_tools import _find_layer, _project


_RELATIONS = {"intersects", "contains", "within", "nearby"}


def _vector_target(project, layer_id, name, label):
    layer = _find_layer(project, layer_id, name)
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid() or layer.geometryType() < 0:
        raise ValueError(f"{label}必须是具有几何对象的有效矢量图层。")
    return layer


def _same_crs(first, second):
    first_crs, second_crs = first.crs(), second.crs()
    if not first_crs.isValid() or not second_crs.isValid():
        raise ValueError("空间关系预览要求两个图层都有有效 CRS。")
    if first_crs != second_crs:
        raise ValueError("两个图层 CRS 不一致；请先明确坐标处理或生成重投影计划。")


def _relation_matches(first_geometry, second_geometry, relation, distance):
    if relation == "intersects":
        return first_geometry.intersects(second_geometry)
    if relation == "contains":
        return first_geometry.contains(second_geometry)
    if relation == "within":
        return first_geometry.within(second_geometry)
    return first_geometry.distance(second_geometry) <= distance


def spatial_query_preview(args: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded preview without selecting or changing either source layer."""
    project = _project(args)
    input_layer = _vector_target(project, args.get("input_layer_id"), args.get("input_name"), "输入图层")
    reference_layer = _vector_target(project, args.get("reference_layer_id"), args.get("reference_name"), "关系图层")
    _same_crs(input_layer, reference_layer)
    relation = args.get("relation")
    if relation not in _RELATIONS:
        raise ValueError("relation 仅支持 intersects、contains、within 或 nearby。")
    distance = args.get("distance")
    if relation == "nearby":
        if input_layer.crs().mapUnits() != reference_layer.crs().mapUnits() or input_layer.crs().isGeographic():
            raise ValueError("nearby 仅支持相同的投影 CRS；请勿把经纬度单位当作距离。")
        try:
            distance = float(distance)
        except (TypeError, ValueError) as exc:
            raise ValueError("nearby 必须提供大于 0 的 distance。") from exc
        if distance <= 0:
            raise ValueError("nearby 必须提供大于 0 的 distance。")
    else:
        distance = None
    sample_limit = _limit(args.get("sample_limit", MAX_SAMPLE))
    reference_features = list(reference_layer.getFeatures())
    if len(reference_features) > MAX_SCAN:
        raise ValueError(f"关系图层超过 {MAX_SCAN} 个要素，当前预览拒绝无界扫描。")
    matched_ids, sample, scanned = [], [], 0
    for feature in input_layer.getFeatures():
        scanned += 1
        if scanned > MAX_SCAN:
            raise ValueError(f"输入图层超过 {MAX_SCAN} 个要素，当前预览拒绝无界扫描。")
        geometry = feature.geometry()
        if geometry is None or geometry.isNull() or geometry.isEmpty():
            continue
        matched_reference_ids = []
        for reference in reference_features:
            reference_geometry = reference.geometry()
            if reference_geometry is None or reference_geometry.isNull() or reference_geometry.isEmpty():
                continue
            if _relation_matches(geometry, reference_geometry, relation, distance):
                matched_reference_ids.append(reference.id())
        if matched_reference_ids:
            matched_ids.append(feature.id())
            if len(sample) < sample_limit:
                sample.append({"feature_id": feature.id(), "matched_reference_ids": matched_reference_ids[:sample_limit]})
    return {
        "input_layer_id": input_layer.id(), "input_layer_name": input_layer.name(),
        "reference_layer_id": reference_layer.id(), "reference_layer_name": reference_layer.name(),
        "crs": input_layer.crs().authid(), "relation": relation, "distance": distance,
        "matched_count": len(matched_ids), "matched_feature_ids": matched_ids,
        "sample": sample, "sample_limit": sample_limit, "scan_limit": MAX_SCAN,
        "selection_changed": False, "project_changed": False,
    }


def query_specs(ToolSpec, PermissionLevel):
    target = {"input_layer_id": {"type": "string"}, "input_name": {"type": "string"},
              "reference_layer_id": {"type": "string"}, "reference_name": {"type": "string"}}
    return [ToolSpec(
        "spatial_query_preview", "预览两个矢量图层的有限空间关系结果，不改变选择集或项目",
        PermissionLevel.READ_ONLY, spatial_query_preview,
        {"type": "object", "properties": {**target, "relation": {"type": "string", "enum": sorted(_RELATIONS)},
         "distance": {"type": "number", "exclusiveMinimum": 0},
         "sample_limit": {"type": "integer", "minimum": 1, "maximum": MAX_SAMPLE}},
         "required": ["relation"], "additionalProperties": False},
    )]