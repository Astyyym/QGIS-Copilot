"""Runtime discovery of raster Processing capabilities; never registers writers."""
from __future__ import annotations

from typing import Any

from qgis.core import QgsApplication


CANDIDATE_ALGORITHMS = (
    "gdal:slope", "gdal:aspect", "gdal:contour", "gdal:translate",
    "native:pixelstopoints", "native:virtualraster",
)


def probe_raster_processing(_args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Report only algorithms actually present in the active QGIS registry."""
    registry = QgsApplication.processingRegistry()
    providers = []
    for provider in registry.providers():
        provider_id = provider.id()
        if provider_id.lower() in {"gdal", "native", "grass", "saga"}:
            providers.append({"id": provider_id, "name": provider.name(), "active": bool(provider.isActive())})
    algorithms = []
    for algorithm_id in CANDIDATE_ALGORITHMS:
        algorithm = registry.algorithmById(algorithm_id)
        if algorithm is not None and algorithm.provider().isActive():
            algorithms.append({"id": algorithm.id(), "name": algorithm.displayName(), "provider": algorithm.provider().id()})
    return {
        "processing_initialized": bool(providers),
        "providers": providers,
        "algorithms": algorithms,
        "available_algorithm_count": len(algorithms),
        "not_registered": True,
        "side_effects": {"project_changed": False, "files_created": False, "processing_started": False},
    }


def provider_probe_specs(ToolSpec, PermissionLevel):
    return [ToolSpec("probe_raster_processing", "探测当前 QGIS 实际可用的栅格 provider 和候选算法摘要，不执行算法", PermissionLevel.READ_ONLY, probe_raster_processing, {"type": "object", "properties": {}, "additionalProperties": False})]
