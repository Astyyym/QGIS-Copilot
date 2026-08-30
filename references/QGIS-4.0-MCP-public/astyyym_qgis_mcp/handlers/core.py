"""Shared utilities for QGIS MCP plugin handlers.

Auto-backup: copies source file to project_dir/_backup/ before destructive ops.
Auto-add: adds file-based results to the project (no virtual/memory layers).
"""
import os, shutil, datetime
from qgis.core import QgsProject, QgsVectorLayer


def backup_source(layer):
    """Copy the layer's source file to project_dir/_backup/ with timestamp.
    Returns backup path, or None if layer has no file source."""
    source = layer.source()
    if not source or not os.path.isfile(source):
        return None

    # Find project dir for _backup/
    project = QgsProject.instance()
    proj_path = project.fileName()
    if not proj_path:
        backup_dir = os.path.join(os.path.dirname(source), "_backup")
    else:
        backup_dir = os.path.join(os.path.dirname(proj_path), "_backup")

    os.makedirs(backup_dir, exist_ok=True)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    basename = os.path.basename(source)
    name, ext = os.path.splitext(basename)

    # For shapefiles, copy all companion files (.shp, .dbf, .prj, .shx, .cpg)
    backed_up = []
    if ext.lower() == ".shp":
        base_dir = os.path.dirname(source)
        base_no_ext = os.path.join(base_dir, name)
        for comp_ext in [".shp", ".dbf", ".prj", ".shx", ".cpg", ".qpj"]:
            comp_path = base_no_ext + comp_ext
            if os.path.isfile(comp_path):
                dest = os.path.join(backup_dir, f"{name}_{ts}{comp_ext}")
                shutil.copy2(comp_path, dest)
                backed_up.append(dest)
        backup_path = os.path.join(backup_dir, f"{name}_{ts}.shp")
    else:
        # GPKG or other single-file format
        backup_path = os.path.join(backup_dir, f"{name}_{ts}{ext}")
        shutil.copy2(source, backup_path)
        backed_up.append(backup_path)

    return backup_path


def add_to_project(file_path, layer_name=None, replace_if_exists=True):
    """Add a file-based layer to the project. Returns layer_id or None.
    No memory/virtual layers — always loads from file."""
    project = QgsProject.instance()
    if not os.path.isfile(file_path):
        return None

    # Determine layer name from filename if not given
    if not layer_name:
        layer_name = os.path.splitext(os.path.basename(file_path))[0]

    # Check if a layer with this name already exists
    existing = None
    for l in project.mapLayers().values():
        if l.name() == layer_name and replace_if_exists:
            existing = l
            break

    # Try vector first, then raster
    layer = QgsVectorLayer(file_path, layer_name, "ogr")
    if layer.isValid():
        if existing:
            project.removeMapLayer(existing)
        project.addMapLayer(layer)
        return layer.id()

    # Raster fallback
    if file_path.lower().endswith((".tif", ".tiff", ".img", ".asc")):
        from qgis.core import QgsRasterLayer
        rl = QgsRasterLayer(file_path, layer_name)
        if rl.isValid():
            if existing:
                project.removeMapLayer(existing)
            project.addMapLayer(rl)
            return rl.id()

    return None
