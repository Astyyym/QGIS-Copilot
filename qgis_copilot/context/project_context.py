"""Bounded, JSON-safe summaries of the current QGIS project."""

from __future__ import annotations


MAX_PROJECT_LAYERS = 100


def _safe(value):
    return "" if value is None else str(value)


def _field_schema(layer):
    """Return vector field metadata; raster layers do not expose attribute fields."""
    if not hasattr(layer, "fields"):
        return []
    fields = []
    for index, field in enumerate(layer.fields()):
        fields.append({
            "name": _safe(field.name()),
            "type": int(field.type()) if hasattr(field, "type") else None,
            "type_name": _safe(field.typeName()) if hasattr(field, "typeName") else "",
            "length": int(field.length()) if hasattr(field, "length") else None,
            "precision": int(field.precision()) if hasattr(field, "precision") else None,
            "alias": _safe(layer.attributeAlias(index)) if hasattr(layer, "attributeAlias") else "",
        })
    return fields


def _layer_summary(layer, *, include_details: bool = True):
    """Return JSON-safe layer metadata; details stay out of initial model context."""
    geometry = _safe(layer.geometryType()) if hasattr(layer, "geometryType") else ""
    crs = layer.crs() if hasattr(layer, "crs") else None
    summary = {
        "id": _safe(layer.id()),
        "name": _safe(layer.name()),
        "provider": _safe(layer.providerType()),
        "type": _safe(layer.type()),
        "geometry_type": geometry,
        "crs": _safe(crs.authid()) if crs else "",
        "feature_count": int(layer.featureCount()) if hasattr(layer, "featureCount") else None,
    }
    if include_details:
        summary.update({
            "source": _safe(layer.source()),
            "crs_description": _safe(crs.description()) if crs and hasattr(crs, "description") else "",
            "extent": _safe(layer.extent().toString()) if hasattr(layer, "extent") else "",
            "selected_count": len(layer.selectedFeatureIds()) if hasattr(layer, "selectedFeatureIds") else 0,
            "fields": _field_schema(layer),
        })
    return summary


def _project_and_layers(project):
    if project is None:
        from qgis.core import QgsProject
        project = QgsProject.instance()
    return project, list(project.mapLayers().values()) if project else []


def _validated_limit(max_layers: int) -> int:
    max_layers = int(max_layers)
    if not 1 <= max_layers <= MAX_PROJECT_LAYERS:
        raise ValueError(f"max_layers 必须在 1 到 {MAX_PROJECT_LAYERS} 之间。")
    return max_layers


def build_project_summary(project=None, max_layers: int = MAX_PROJECT_LAYERS) -> dict:
    """Return detailed bounded metadata for read-only tool results, never attributes."""
    max_layers = _validated_limit(max_layers)
    project, layers = _project_and_layers(project)
    return {
        "project": {
            "file_path": _safe(project.fileName()) if project and hasattr(project, "fileName") else "",
            "title": _safe(project.title()) if project and hasattr(project, "title") else "",
            "crs": _safe(project.crs().authid()) if project and hasattr(project, "crs") else "",
            "layer_count": len(layers),
        },
        "layers": [_layer_summary(layer, include_details=True) for layer in layers[:max_layers]],
        "truncated": len(layers) > max_layers,
    }


def build_model_project_context(project=None, max_layers: int = MAX_PROJECT_LAYERS) -> dict:
    """Return only discovery metadata sent with a first model request.

    Fields, sources, extents, selection and attributes are available only through
    explicit read-only tools, keeping prompts small and data exposure bounded.
    """
    max_layers = _validated_limit(max_layers)
    project, layers = _project_and_layers(project)
    return {
        "project": {
            "title": _safe(project.title()) if project and hasattr(project, "title") else "",
            "crs": _safe(project.crs().authid()) if project and hasattr(project, "crs") else "",
            "layer_count": len(layers),
        },
        "layers": [_layer_summary(layer, include_details=False) for layer in layers[:max_layers]],
        "truncated": len(layers) > max_layers,
    }
