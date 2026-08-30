import os
import io
import sys
import json
import socket
import traceback
import datetime
from qgis.core import *
from qgis.gui import *
from qgis.PyQt.QtCore import QObject, pyqtSignal, QTimer, Qt, QSize
from qgis.PyQt.QtWidgets import QAction, QDockWidget, QVBoxLayout, QLabel, QPushButton, QSpinBox, QWidget
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.utils import active_plugins

# Plugin utility modules
from .handlers.core import backup_source, add_to_project

# ---------------------------------------------------------------------------
# QGIS 3 / 4 compatibility helpers
# ---------------------------------------------------------------------------

def _qgis_major_version():
    """Return the QGIS major version as an integer (3 or 4)."""
    try:
        return int(Qgis.version().split(".")[0])
    except Exception:
        return 3  # safe fallback


_QGIS_MAJOR = _qgis_major_version()


def _is_vector_layer(layer):
    """Check whether *layer* is a vector layer (works on QGIS 3 and 4)."""
    if _QGIS_MAJOR >= 4:
        return layer.type() == Qgis.LayerType.Vector
    return layer.type() == QgsMapLayer.VectorLayer


def _is_raster_layer(layer):
    """Check whether *layer* is a raster layer (works on QGIS 3 and 4)."""
    if _QGIS_MAJOR >= 4:
        return layer.type() == Qgis.LayerType.Raster
    return layer.type() == QgsMapLayer.RasterLayer


def _geometry_type_str(geometry):
    """Return a human-readable string for the geometry type."""
    gt = geometry.type()
    # In QGIS 4 this is Qgis.GeometryType enum; in 3 it's an int.
    # Converting to int works on both versions.
    _type_names = {0: "Point", 1: "Line", 2: "Polygon", 3: "Unknown", 4: "Null"}
    return _type_names.get(int(gt), str(gt))


def _geometry_type_str_from_layer(layer):
    """Return geometry type string from a layer (works on QGIS 3 & 4)."""
    if _QGIS_MAJOR >= 4:
        return str(layer.geometryType()).split('.')[-1]
    gt = layer.geometryType()
    _type_names = {0: "Point", 1: "Line", 2: "Polygon", 3: "Unknown", 4: "Null"}
    return _type_names.get(int(gt), str(gt))


def _msg_level(level_name):
    """Return the Qgis message level constant by name ('Critical', 'Warning', 'Info')."""
    if _QGIS_MAJOR >= 4:
        return getattr(Qgis.MessageLevel, level_name)
    return getattr(Qgis, level_name)


class QgisMCPServer(QObject):
    """Server class to handle socket connections and execute QGIS commands"""

    def __init__(self, host='0.0.0.0', port=9877, iface=None):
        super().__init__()
        self.host = host
        self.port = port
        self.iface = iface
        self.running = False
        self.socket = None
        self.client = None
        self.buffer = b''
        self.timer = None
        self.operation_log = []
        self.operation_log_limit = 200
        # Build handlers dict once, not per-command
        self.handlers = {
            "ping": self.ping,
            "get_qgis_info": self.get_qgis_info,
            "load_project": self.load_project,
            "get_project_info": self.get_project_info,
            "execute_code": self.execute_code,
            "add_vector_layer": self.add_vector_layer,
            "add_raster_layer": self.add_raster_layer,
            "get_layers": self.get_layers,
            "remove_layer": self.remove_layer,
            "zoom_to_layer": self.zoom_to_layer,
            "get_layer_features": self.get_layer_features,
            "execute_processing": self.execute_processing,
            "save_project": self.save_project,
            "render_map": self.render_map,
            "create_new_project": self.create_new_project,
            # Custom additions
            "reorder_layers": self.reorder_layers,
            "rename_layer": self.rename_layer,
            "export_layer": self.export_layer,
            "zoom_to_feature": self.zoom_to_feature,
            "create_buffer": self.create_buffer,
            "add_field": self.add_field,
            "delete_fields": self.delete_fields,
            "reorder_fields": self.reorder_fields,
            "get_fields": self.get_fields,
            # Urban planning / surveying workflow additions
            "validate_layer": self.validate_layer,
            "check_crs_consistency": self.check_crs_consistency,
            "reproject_layer": self.reproject_layer,
            "clip_vector": self.clip_vector,
            "intersection": self.intersection,
            "difference": self.difference,
            "join_attributes_by_location": self.join_attributes_by_location,
            "calculate_area_fields": self.calculate_area_fields,
            "summarize_area_by_zone": self.summarize_area_by_zone,
            "select_by_expression": self.select_by_expression,
            "export_selected_features": self.export_selected_features,
            "clip_raster_by_mask": self.clip_raster_by_mask,
            "zonal_statistics": self.zonal_statistics,
            "cad_to_gpkg": self.cad_to_gpkg,
            "slope": self.slope,
            "aspect": self.aspect,
            "contour": self.contour,
            "create_grid": self.create_grid,
            "idw_interpolation": self.idw_interpolation,
            "cut_fill": self.cut_fill,
            # Project structure, controlled editing, and delivery diagnostics
            "inspect_project_state": self.inspect_project_state,
            "get_layer_tree": self.get_layer_tree,
            "inspect_layer": self.inspect_layer,
            "get_project_diagnostics": self.get_project_diagnostics,
            "query_features": self.query_features,
            "get_layer_statistics": self.get_layer_statistics,
            "validate_expression": self.validate_expression,
            "manage_selection": self.manage_selection,
            "calculate_field": self.calculate_field,
            "update_feature_attributes": self.update_feature_attributes,
            "delete_features": self.delete_features,
            "validate_project_for_delivery": self.validate_project_for_delivery,
            "validate_processing_result": self.validate_processing_result,
            "verify_output_file": self.verify_output_file,
            "get_operation_log": self.get_operation_log,
            "capture_project_state": self.capture_project_state,
        }

    def start(self):
        """Start the server"""
        self.running = True
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.socket.bind((self.host, self.port))
            self.socket.listen(1)
            self.socket.setblocking(False)

            # Create a timer to process server operations
            self.timer = QTimer()
            self.timer.timeout.connect(self.process_server)
            self.timer.start(100)  # 100ms interval

            QgsMessageLog.logMessage(f"Astyyym QGIS MCP server started on {self.host}:{self.port}", "Astyyym QGIS MCP")
            return True
        except Exception as e:
            QgsMessageLog.logMessage(f"Failed to start server: {str(e)}", "Astyyym QGIS MCP", _msg_level("Critical"))
            self.stop()
            return False

    def stop(self):
        """Stop the server"""
        self.running = False

        if self.timer:
            self.timer.stop()
            self.timer = None

        if self.socket:
            self.socket.close()
        if self.client:
            self.client.close()

        self.socket = None
        self.client = None
        QgsMessageLog.logMessage("Astyyym QGIS MCP server stopped", "Astyyym QGIS MCP")

    def process_server(self):
        """Process server operations (called by timer)"""
        if not self.running:
            return

        try:
            # Accept new connections
            if not self.client and self.socket:
                try:
                    self.client, address = self.socket.accept()
                    QgsMessageLog.logMessage(f"Connected to client: {address}", "Astyyym QGIS MCP")
                except BlockingIOError:
                    pass  # No connection waiting
                except Exception as e:
                    QgsMessageLog.logMessage(f"Error accepting connection: {str(e)}", "Astyyym QGIS MCP", _msg_level("Warning"))

            # Process existing connection
            if self.client:
                try:
                    # Try to receive data
                    try:
                        data = self.client.recv(8192)
                        if data:
                            self.buffer += data
                            # Try to process complete messages
                            try:
                                # Attempt to parse the buffer as JSON
                                command = json.loads(self.buffer.decode('utf-8'))
                                # If successful, clear the buffer and process command
                                self.buffer = b''
                                response = self.execute_command(command)
                                response_bytes = json.dumps(response).encode('utf-8')
                                # 4-byte big-endian length prefix for message framing
                                self.client.sendall(len(response_bytes).to_bytes(4, 'big') + response_bytes)
                            except json.JSONDecodeError:
                                # Incomplete data, keep in buffer
                                pass
                        else:
                            # Connection closed by client
                            QgsMessageLog.logMessage("Client disconnected", "Astyyym QGIS MCP")
                            self.client.close()
                            self.client = None
                            self.buffer = b''
                    except BlockingIOError:
                        pass  # No data available
                    except Exception as e:
                        QgsMessageLog.logMessage(f"Error receiving data: {str(e)}", "Astyyym QGIS MCP", _msg_level("Warning"))
                        self.client.close()
                        self.client = None
                        self.buffer = b''

                except Exception as e:
                    QgsMessageLog.logMessage(f"Error with client: {str(e)}", "Astyyym QGIS MCP", _msg_level("Warning"))
                    if self.client:
                        self.client.close()
                        self.client = None
                    self.buffer = b''

        except Exception as e:
            QgsMessageLog.logMessage(f"Server error: {str(e)}", "Astyyym QGIS MCP", _msg_level("Critical"))

    def execute_command(self, command):
        """Execute a command"""
        cmd_type = command.get("type")
        params = command.get("params", {})
        started_at = datetime.datetime.now().isoformat(timespec="seconds")
        try:
            handler = self.handlers.get(cmd_type)
            if handler:
                try:
                    QgsMessageLog.logMessage(f"Executing handler for {cmd_type}", "Astyyym QGIS MCP")
                    result = handler(**params)
                    QgsMessageLog.logMessage(f"Handler execution complete", "Astyyym QGIS MCP")
                    self._record_operation(cmd_type, params, "success", started_at, result)
                    return {"status": "success", "result": result}
                except Exception as e:
                    self._record_operation(cmd_type, params, "error", started_at, {"message": str(e)})
                    QgsMessageLog.logMessage(f"Error in handler: {str(e)}", "Astyyym QGIS MCP", _msg_level("Critical"))
                    traceback.print_exc()
                    return {"status": "error", "message": str(e)}
            self._record_operation(cmd_type, params, "error", started_at, {"message": "Unknown command type"})
            return {"status": "error", "message": f"Unknown command type: {cmd_type}"}
        except Exception as e:
            self._record_operation(cmd_type, params, "error", started_at, {"message": str(e)})
            QgsMessageLog.logMessage(f"Error executing command: {str(e)}", "Astyyym QGIS MCP", _msg_level("Critical"))
            traceback.print_exc()
            return {"status": "error", "message": str(e)}

    # Command handlers
    def ping(self, **kwargs):
        """Simple ping command"""
        return {"pong": True}

    def get_qgis_info(self, **kwargs):
        """Get basic QGIS information"""
        return {
            "qgis_version": Qgis.version(),
            "qgis_major": _QGIS_MAJOR,
            "profile_folder": QgsApplication.qgisSettingsDirPath(),
            "plugins_count": len(active_plugins)
        }

    def get_project_info(self, **kwargs):
        """Get information about the current QGIS project"""
        project = QgsProject.instance()

        # Get basic project information
        info = {
            "filename": project.fileName(),
            "title": project.title(),
            "layer_count": len(project.mapLayers()),
            "crs": project.crs().authid(),
            "layers": []
        }

        # Add basic layer information (limit to 10 layers for performance)
        layers = list(project.mapLayers().values())
        for i, layer in enumerate(layers):
            if i >= 10:  # Limit to 10 layers
                break

            layer_info = {
                "id": layer.id(),
                "name": layer.name(),
                "type": self._get_layer_type(layer),
            }

            root = project.layerTreeRoot()
            tree_layer = root.findLayer(layer.id())
            if tree_layer is None:
                layer_info["visible"] = False
            else:
                layer_info["visible"] = layer.isValid() and tree_layer.isVisible()

            info["layers"].append(layer_info)

        return info

    def _get_layer_type(self, layer):
        """Helper to get layer type as string"""
        if _is_vector_layer(layer):
            return f"vector_{_geometry_type_str_from_layer(layer)}"
        elif _is_raster_layer(layer):
            return "raster"
        else:
            return str(layer.type())

    def _get_group_path(self, tree_node):
        """Return the full group path for a layer tree node."""
        parts = []
        parent = tree_node.parent()
        while parent and parent.name():
            parts.append(parent.name())
            parent = parent.parent()
        parts.reverse()
        return "/".join(parts) if parts else ""

    def execute_code(self, code, **kwargs):
        """Execute arbitrary PyQGIS code"""

        # Capture stdout and stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        # Store original stdout and stderr
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        try:
            # Redirect stdout and stderr
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture

            # Create a local namespace for execution
            namespace = {
                "qgis": Qgis,
                "QgsProject": QgsProject,
                "iface": self.iface,
                "QgsApplication": QgsApplication,
                "QgsVectorLayer": QgsVectorLayer,
                "QgsRasterLayer": QgsRasterLayer,
                "QgsCoordinateReferenceSystem": QgsCoordinateReferenceSystem
            }

            # Execute the code
            exec(code, namespace)

            # Restore stdout and stderr
            sys.stdout = original_stdout
            sys.stderr = original_stderr

            return {
                "executed": True,
                "stdout": stdout_capture.getvalue(),
                "stderr": stderr_capture.getvalue()
            }
        except Exception as e:
            # Generate full traceback
            error_traceback = traceback.format_exc()

            # Restore stdout and stderr in case of exception
            sys.stdout = original_stdout
            sys.stderr = original_stderr

            return {
                "executed": False,
                "error": str(e),
                "traceback": error_traceback,
                "stdout": stdout_capture.getvalue(),
                "stderr": stderr_capture.getvalue()
            }

    def add_vector_layer(self, path, name=None, provider="ogr", **kwargs):
        """Add a vector layer to the project"""
        if not name:
            name = os.path.basename(path)

        # Create the layer
        layer = QgsVectorLayer(path, name, provider)

        if not layer.isValid():
            raise Exception(f"Layer is not valid: {path}")

        # Add to project
        QgsProject.instance().addMapLayer(layer)

        return {
            "id": layer.id(),
            "name": layer.name(),
            "type": self._get_layer_type(layer),
            "feature_count": layer.featureCount()
        }

    def add_raster_layer(self, path, name=None, provider="gdal", **kwargs):
        """Add a raster layer to the project"""
        if not name:
            name = os.path.basename(path)

        # Create the layer
        layer = QgsRasterLayer(path, name, provider)

        if not layer.isValid():
            raise Exception(f"Layer is not valid: {path}")

        # Add to project
        QgsProject.instance().addMapLayer(layer)

        return {
            "id": layer.id(),
            "name": layer.name(),
            "type": "raster",
            "width": layer.width(),
            "height": layer.height()
        }

    def get_layers(self, **kwargs):
        """Get all layers in the project"""
        project = QgsProject.instance()
        layers = []

        for layer_id, layer in project.mapLayers().items():
            layer_info = {
                "id": layer_id,
                "name": layer.name(),
                "type": self._get_layer_type(layer),
            }

            root = project.layerTreeRoot()
            tree_layer = root.findLayer(layer_id)
            if tree_layer is None:
                layer_info["visible"] = False
                layer_info["group"] = ""
            else:
                layer_info["visible"] = tree_layer.isVisible()
                layer_info["group"] = self._get_group_path(tree_layer)

            # Add type-specific information
            if _is_vector_layer(layer):
                layer_info.update({
                    "feature_count": layer.featureCount(),
                    "geometry_type": _geometry_type_str_from_layer(layer)
                })
            elif _is_raster_layer(layer):
                layer_info.update({
                    "width": layer.width(),
                    "height": layer.height()
                })

            layers.append(layer_info)

        return layers

    def remove_layer(self, layer_id, **kwargs):
        """Remove a layer from the project"""
        project = QgsProject.instance()

        if layer_id in project.mapLayers():
            project.removeMapLayer(layer_id)
            return {"removed": layer_id}
        else:
            raise Exception(f"Layer not found: {layer_id}")

    def zoom_to_layer(self, layer_id, **kwargs):
        """Zoom to a layer's extent"""
        project = QgsProject.instance()

        if layer_id in project.mapLayers():
            layer = project.mapLayer(layer_id)
            canvas = self.iface.mapCanvas()
            canvas.setExtent(layer.extent())
            canvas.refresh()
            return {"zoomed_to": layer_id}
        else:
            raise Exception(f"Layer not found: {layer_id}")

    def get_layer_features(self, layer_id, limit=10, **kwargs):
        """Get features from a vector layer"""
        project = QgsProject.instance()

        if layer_id in project.mapLayers():
            layer = project.mapLayer(layer_id)

            if not _is_vector_layer(layer):
                raise Exception(f"Layer is not a vector layer: {layer_id}")

            features = []
            for i, feature in enumerate(layer.getFeatures()):
                if i >= limit:
                    break

                # Extract attributes
                attrs = {}
                for field in layer.fields():
                    val = feature.attribute(field.name())
                    if val is None or (hasattr(val, 'isNull') and val.isNull()):
                        attrs[field.name()] = None
                    else:
                        try:
                            json.dumps(val)
                            attrs[field.name()] = val
                        except (TypeError, ValueError):
                            attrs[field.name()] = str(val)

                # Extract geometry if available
                geom = None
                if feature.hasGeometry():
                    geom = {
                        "type": _geometry_type_str(feature.geometry()),
                        "wkt": feature.geometry().asWkt(precision=4)
                    }

                features.append({
                    "id": feature.id(),
                    "attributes": attrs,
                    "geometry": geom
                })

            return {
                "layer_id": layer_id,
                "feature_count": layer.featureCount(),
                "features": features,
                "fields": [field.name() for field in layer.fields()]
            }
        else:
            raise Exception(f"Layer not found: {layer_id}")

    def execute_processing(self, algorithm, parameters, **kwargs):
        """Execute a processing algorithm"""
        try:
            import processing
            from qgis.core import QgsProcessingContext, QgsProcessingFeedback
            context = QgsProcessingContext()
            context.setProject(QgsProject.instance())
            feedback = QgsProcessingFeedback()
            result = processing.run(algorithm, parameters, context=context, feedback=feedback)
            return {
                "algorithm": algorithm,
                "result": {k: str(v) for k, v in result.items()}  # Convert values to strings for JSON
            }
        except Exception as e:
            raise Exception(f"Processing error: {str(e)}")

    def save_project(self, path=None, **kwargs):
        """Save the current project"""
        project = QgsProject.instance()

        if not path and not project.fileName():
            raise Exception("No project path specified and no current project path")

        save_path = path if path else project.fileName()
        if project.write(save_path):
            return {"saved": save_path}
        else:
            raise Exception(f"Failed to save project to {save_path}")

    def load_project(self, path, **kwargs):
        """Load a project"""
        project = QgsProject.instance()

        if project.read(path):
            self.iface.mapCanvas().refresh()
            return {
                "loaded": path,
                "layer_count": len(project.mapLayers())
            }
        else:
            raise Exception(f"Failed to load project from {path}")

    def create_new_project(self, path, **kwargs):
        """
        Creates a new QGIS project and saves it at the specified path.
        If a project is already loaded, it clears it before creating the new one.

        :param project_path: Full path where the project will be saved
                            (e.g., 'C:/path/to/project.qgz')
        """
        project = QgsProject.instance()

        if project.fileName():
            project.clear()

        project.setFileName(path)
        self.iface.mapCanvas().refresh()

        # Save the project
        if project.write():
            return {
                "created": f"Project created and saved successfully at: {path}",
                "layer_count": len(project.mapLayers())
            }
        else:
            raise Exception(f"Failed to save project to {path}")

    def render_map(self, path, width=800, height=600, **kwargs):
        """Render the current map view to an image"""
        try:
            # Create map settings
            ms = QgsMapSettings()

            # Set layers to render
            layers = list(QgsProject.instance().mapLayers().values())
            ms.setLayers(layers)

            # Set map canvas properties
            rect = self.iface.mapCanvas().extent()
            ms.setExtent(rect)
            ms.setOutputSize(QSize(width, height))
            ms.setBackgroundColor(QColor(255, 255, 255))
            ms.setOutputDpi(96)

            # Create the render
            render = QgsMapRendererParallelJob(ms)

            # Start rendering
            render.start()
            render.waitForFinished()

            # Get the image and save
            img = render.renderedImage()
            if img.save(path):
                return {
                    "rendered": True,
                    "path": path,
                    "width": width,
                    "height": height
                }
            else:
                raise Exception(f"Failed to save rendered image to {path}")

        except Exception as e:
            raise Exception(f"Render error: {str(e)}")

    # -----------------------------------------------------------------------
    # Custom handler additions
    # -----------------------------------------------------------------------

    def reorder_layers(self, layer_ids, **kwargs):
        """Reorder layers in the layer tree.
        First in list = top of tree (rendered last/on top).
        Last in list = bottom of tree (rendered first/behind).
        :param layer_ids: List of layer IDs in desired top-to-bottom order
        """
        project = QgsProject.instance()
        layers = []
        names = []
        for lid in layer_ids:
            layer = project.mapLayer(lid)
            if layer:
                layers.append(layer)
                names.append(layer.name())
        if not layers:
            raise Exception("No valid layers found in layer_ids")
        root = project.layerTreeRoot()
        root.reorderGroupLayers(layers)
        return {"reordered": names}

    def rename_layer(self, layer_id, name, **kwargs):
        """Rename a layer.
        :param layer_id: ID of the layer to rename
        :param name: New layer name
        """
        project = QgsProject.instance()
        layer = project.mapLayer(layer_id)
        if not layer:
            raise Exception(f"Layer not found: {layer_id}")
        old_name = layer.name()
        layer.setName(name)
        return {"layer_id": layer_id, "old_name": old_name, "new_name": name}

    def export_layer(self, layer_id, output_path, **kwargs):
        """Export a layer to a file.
        Vectors are saved as GPKG, rasters copy the source file.
        :param layer_id: ID of the layer to export
        :param output_path: Full destination path
        """
        import os, shutil
        project = QgsProject.instance()
        layer = project.mapLayer(layer_id)
        if not layer:
            raise Exception(f"Layer not found: {layer_id}")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        name = layer.name()
        export_type = "unknown"

        if layer.type() == 0:  # Vector
            from qgis.core import QgsVectorFileWriter
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.fileEncoding = "UTF-8"

            err, err_msg, out_path, out_name = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, output_path, project.transformContext(), options
            )
            if err != QgsVectorFileWriter.WriterError.NoError:
                raise Exception(f"Vector export failed: {err_msg}")
            export_type = "vector"
        else:  # Raster
            shutil.copy2(layer.source(), output_path)
            export_type = "raster"

        # Auto-add to project (file-based, no virtual layers)
        new_id = add_to_project(output_path)
        result = {
            "layer_id": layer_id,
            "layer_name": name,
            "output": output_path,
            "type": export_type
        }
        if new_id:
            result["new_layer_id"] = new_id

        return result

    def zoom_to_feature(self, layer_id, expression, **kwargs):
        """Zoom to the first feature matching a QGIS expression.
        :param layer_id: Layer ID
        :param expression: QGIS expression string, e.g. '"省" = \'广东省\''
        """
        from qgis.core import QgsExpression, QgsFeatureRequest
        project = QgsProject.instance()
        layer = project.mapLayer(layer_id)
        if not layer:
            raise Exception(f"Layer not found: {layer_id}")

        expr = QgsExpression(expression)
        request = QgsFeatureRequest(expr)
        feature = next(layer.getFeatures(request), None)
        if not feature:
            raise Exception(f"No feature matching expression: {expression}")

        extent = feature.geometry().boundingBox()
        canvas = self.iface.mapCanvas()
        canvas.setExtent(extent)
        canvas.refresh()
        return {
            "zoomed_to": expression,
            "extent": {
                "xMin": extent.xMinimum(),
                "yMin": extent.yMinimum(),
                "xMax": extent.xMaximum(),
                "yMax": extent.yMaximum()
            }
        }

    def get_fields(self, layer_id, **kwargs):
        """Return field names and types for a vector layer.

        :param layer_id: ID of the vector layer
        """
        from qgis.core import QgsProject
        project = QgsProject.instance()
        layer = project.mapLayer(layer_id)
        if not layer:
            raise Exception(f"Layer not found: {layer_id}")

        fields = []
        for f in layer.fields():
            fields.append({
                "name": f.name(),
                "type": f.typeName(),
                "length": f.length(),
                "precision": f.precision()
            })

        return {
            "layer_name": layer.name(),
            "feature_count": layer.featureCount(),
            "fields": fields
        }

    def create_buffer(self, layer_id, distance, output_path, dissolve=True, segments=32, **kwargs):
        """Create buffers around features in a vector layer.
        Auto-handles CRS reprojection (4326 -> projected -> buffer -> original CRS).

        :param layer_id: ID of the source vector layer
        :param distance: Buffer distance in meters
        :param output_path: Full path for output file (.gpkg)
        :param dissolve: If True, dissolve overlapping buffers
        :param segments: Buffer smoothness (default 32)
        """
        import processing, os, tempfile
        project = QgsProject.instance()
        input_layer = project.mapLayer(layer_id)
        if not input_layer:
            raise Exception(f"Layer not found: {layer_id}")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        src_crs = input_layer.crs().authid()
        tmp_files = []
        current = input_layer

        if src_crs != "EPSG:3857":
            t1 = os.path.join(tempfile.gettempdir(), f"_buf_reproj_{id(input_layer)}.gpkg")
            r = processing.run("native:reprojectlayer", {
                "INPUT": current, "TARGET_CRS": "EPSG:3857", "OUTPUT": t1
            })
            current = r["OUTPUT"]
            tmp_files.append(t1)

        r = processing.run("native:buffer", {
            "INPUT": current, "DISTANCE": distance, "SEGMENTS": segments,
            "DISSOLVE": dissolve, "END_CAP_STYLE": 0, "JOIN_STYLE": 0,
            "MITER_LIMIT": 2,
            "OUTPUT": output_path if src_crs == "EPSG:3857"
                      else os.path.join(tempfile.gettempdir(), f"_buf_result_{id(input_layer)}.gpkg")
        })

        if src_crs != "EPSG:3857":
            t2 = r["OUTPUT"]
            tmp_files.append(t2)
            r = processing.run("native:reprojectlayer", {
                "INPUT": t2, "TARGET_CRS": src_crs, "OUTPUT": output_path
            })

        for f in tmp_files:
            try: os.remove(f)
            except: pass

        # Auto-add to project (file-based, no virtual layers)
        new_id = add_to_project(output_path)
        result = {"output": output_path, "source_layer": input_layer.name(), "distance_m": distance}
        if new_id:
            result["layer_id"] = new_id

        return result

    def add_field(self, layer_id, field_name, field_type="Double", expression=None, rank_by=None, rank_order="desc", **kwargs):
        """Add a field to a vector layer and optionally populate with values.

        :param layer_id: ID of the vector layer
        :param field_name: Name for the new field
        :param field_type: "Integer", "Double" (default), or "String"
        :param expression: QGIS expression to compute field values (e.g. '"A" / "B"')
        :param rank_by: Field name to rank by (alternative to expression)
        :param rank_order: "desc" (default) or "asc"
        """
        from qgis.core import QgsField, QgsExpression, QgsFeatureRequest, QgsProject
        from qgis.PyQt.QtCore import QVariant
        import traceback

        project = QgsProject.instance()
        layer = project.mapLayer(layer_id)
        if not layer:
            raise Exception(f"Layer not found: {layer_id}")

        type_map = {"Integer": QVariant.Int, "Double": QVariant.Double, "String": QVariant.String}
        qt_type = type_map.get(field_type)
        if not qt_type:
            raise Exception(f"Invalid field_type: {field_type}. Use Integer, Double, or String")

        if field_name in [f.name() for f in layer.fields()]:
            raise Exception(f"Field '{field_name}' already exists on layer '{layer.name()}'")

        # Add the field
        layer.dataProvider().addAttributes([QgsField(field_name, qt_type)])
        layer.updateFields()
        result = {"field_added": field_name, "field_type": field_type, "features_updated": 0}

        # Auto-backup before modifying data
        if expression or rank_by:
            backup_path = backup_source(layer)
            if not backup_path:
                QgsMessageLog.logMessage(
                    "WARNING: Could not create backup before modifying data — "
                    "layer has no file source or project not saved",
                    "Astyyym QGIS MCP", _msg_level("Warning")
                )

        # Populate with expression
        if expression:
            expr = QgsExpression(expression)
            if expr.hasParserError():
                raise Exception(f"Expression error: {expr.parserError()}")
            ctx = QgsProject.instance().createExpressionContext()
            layer.startEditing()
            count = 0
            new_idx = layer.fields().indexOf(field_name)
            for feat in layer.getFeatures():
                ctx.setFeature(feat)
                val = expr.evaluate(ctx)
                if expr.hasEvalError():
                    val = None
                if isinstance(val, float):
                    val = round(val, 4)
                layer.changeAttributeValue(feat.id(), new_idx, val)
                count += 1
            layer.commitChanges()
            result["features_updated"] = count
            result["expression"] = expression

        # Or populate with rank
        elif rank_by:
            if rank_by not in [f.name() for f in layer.fields()]:
                raise Exception(f"Sort field '{rank_by}' not found on layer")
            reverse = (rank_order == "desc")
            features = list(layer.getFeatures())
            features.sort(key=lambda f: f.attribute(rank_by) or 0, reverse=reverse)
            layer.startEditing()
            new_idx = layer.fields().indexOf(field_name)
            for rank, feat in enumerate(features, 1):
                layer.changeAttributeValue(feat.id(), new_idx, rank)
            layer.commitChanges()
            result["features_updated"] = len(features)
            result["rank_by"] = rank_by
            result["rank_order"] = rank_order

        return result

    def delete_fields(self, layer_id, field_names, **kwargs):
        """Delete one or more fields from a vector layer.

        :param layer_id: ID of the vector layer
        :param field_names: List of field names to delete (e.g. ["城区人", "WeMapGIS"])
        """
        from qgis.core import QgsProject
        project = QgsProject.instance()
        layer = project.mapLayer(layer_id)
        if not layer:
            raise Exception(f"Layer not found: {layer_id}")

        # Auto-backup before destructive operation
        backup_path = backup_source(layer)
        if not backup_path:
            QgsMessageLog.logMessage(
                "WARNING: Could not create backup before deleting fields — "
                "layer has no file source or project not saved",
                "Astyyym QGIS MCP", _msg_level("Warning")
            )

        existing = [f.name() for f in layer.fields()]
        indices = []
        names_deleted = []
        for name in field_names:
            if name in existing:
                indices.append(existing.index(name))
                names_deleted.append(name)

        if not indices:
            raise Exception(f"None of the specified fields found on layer. Existing: {existing}")

        layer.dataProvider().deleteAttributes(indices)
        layer.updateFields()
        return {"fields_deleted": names_deleted, "count": len(names_deleted)}

    def reorder_fields(self, layer_id, field_order, output_path=None, **kwargs):
        """Safely reorder fields by creating a new layer with the desired order.
        Original file is NEVER modified in-place — always creates a new file.

        :param layer_id: ID of the source vector layer
        :param field_order: Ordered list of field names, e.g. ["fid","省","合计"...]
        :param output_path: Optional output path. If omitted, overwrites source path.
        """
        from qgis.core import (QgsProject, QgsVectorLayer, QgsField, QgsFeature,
            QgsVectorFileWriter, QgsCoordinateTransformContext)
        from qgis.PyQt.QtCore import QVariant
        import os, tempfile, shutil

        project = QgsProject.instance()
        src = project.mapLayer(layer_id)
        if not src:
            raise Exception(f"Layer not found: {layer_id}")

        existing_fields = {f.name(): f for f in src.fields()}
        # Validate all requested fields exist
        for name in field_order:
            if name not in existing_fields and name != src.fields().at(0).name():
                # fid is auto-generated, skip
                if name in [f.name() for f in src.fields()]:
                    continue
                raise Exception(f"Field '{name}' not found on layer. Available: {list(existing_fields.keys())}")

        geom_type = src.geometryType()
        crs = src.crs().authid()
        type_map_str = {QVariant.Int: "integer", QVariant.Double: "double", QVariant.String: "string"}

        # Build field defs in the new order (skip fid — it's auto)
        ordered_defs = []
        for name in field_order:
            if name in existing_fields and name.lower() != "fid":
                f = existing_fields[name]
                qt_type = f.type()
                ordered_defs.append(QgsField(name, qt_type))

        if not ordered_defs:
            raise Exception("No valid fields to order")

        # Determine output: new file path
        src_path = src.source()
        if output_path:
            out_path = output_path
        else:
            base, ext = os.path.splitext(src_path)
            out_path = base + "_reordered.gpkg"

        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

        # Create new layer with ordered fields
        geom_map = {0: "Point", 1: "Line", 2: "Polygon"}
        geom_str = geom_map.get(geom_type, "Point")
        new_src_path = src.source() if output_path else out_path
        new_layer = QgsVectorLayer(f"{geom_str}?crs={crs}", "temp_reorder", "memory")
        new_pr = new_layer.dataProvider()
        new_pr.addAttributes(ordered_defs)
        new_layer.updateFields()

        # Copy features — map old attributes to new field order
        new_fields = {f.name(): i for i, f in enumerate(new_layer.fields())}
        src_fields = {f.name(): i for i, f in enumerate(src.fields())}

        for feat in src.getFeatures():
            new_feat = QgsFeature()
            new_feat.setGeometry(feat.geometry())
            attrs = [None] * len(new_fields)
            for new_name, new_idx in new_fields.items():
                if new_name in src_fields:
                    attrs[new_idx] = feat.attribute(new_name)
            new_feat.setAttributes(attrs)
            new_pr.addFeature(new_feat)

        new_layer.updateExtents()

        # Write to file
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.fileEncoding = "UTF-8"
        err, msg, out, n = QgsVectorFileWriter.writeAsVectorFormatV3(
            new_layer, out_path, project.transformContext(), opts
        )
        if err != QgsVectorFileWriter.WriterError.NoError:
            raise Exception(f"Write failed: {msg}")

        # Add new layer FIRST, then remove old one
        replacement = QgsVectorLayer(out_path, src.name(), "ogr")
        project.addMapLayer(replacement)
        project.removeMapLayer(src)

        return {
            "field_order": field_order,
            "output": out_path,
            "features_copied": n
        }

    def _get_layer(self, layer_id, expected=None):
        project = QgsProject.instance()
        layer = project.mapLayer(layer_id)
        if not layer:
            raise Exception(f"Layer not found: {layer_id}")
        if expected == "vector" and not _is_vector_layer(layer):
            raise Exception(f"Layer is not a vector layer: {layer_id}")
        if expected == "raster" and not _is_raster_layer(layer):
            raise Exception(f"Layer is not a raster layer: {layer_id}")
        return layer

    def _run_file_algorithm(self, algorithm, parameters, output_path, layer_name=None):
        import os
        import processing
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        parameters = dict(parameters)
        parameters["OUTPUT"] = output_path
        result = processing.run(algorithm, parameters)
        new_id = add_to_project(output_path, layer_name=layer_name)
        return {
            "algorithm": algorithm,
            "output": str(result.get("OUTPUT", output_path)),
            "layer_id": new_id,
        }

    def validate_layer(self, layer_id, check_geometry=True, sample_invalid=20, **kwargs):
        """Inspect common data-quality issues for vector/raster layers."""
        layer = self._get_layer(layer_id)
        result = {
            "layer_id": layer_id,
            "layer_name": layer.name(),
            "crs": layer.crs().authid(),
            "is_valid": layer.isValid(),
            "type": "vector" if _is_vector_layer(layer) else "raster" if _is_raster_layer(layer) else "unknown",
        }

        if _is_vector_layer(layer):
            fields = layer.fields()
            field_names = [field.name() for field in fields]
            duplicate_fields = sorted({name for name in field_names if field_names.count(name) > 1})
            empty_geometry_count = 0
            invalid_geometry_ids = []
            for feature in layer.getFeatures():
                geom = feature.geometry()
                if not geom or geom.isEmpty():
                    empty_geometry_count += 1
                    continue
                if check_geometry and not geom.isGeosValid():
                    if len(invalid_geometry_ids) < sample_invalid:
                        invalid_geometry_ids.append(feature.id())
            result.update({
                "geometry_type": _geometry_type_str_from_layer(layer),
                "feature_count": layer.featureCount(),
                "field_count": len(fields),
                "fields": field_names,
                "duplicate_fields": duplicate_fields,
                "empty_geometry_count": empty_geometry_count,
                "invalid_geometry_count_sampled": len(invalid_geometry_ids),
                "invalid_geometry_ids_sample": invalid_geometry_ids,
            })
        elif _is_raster_layer(layer):
            extent = layer.extent()
            result.update({
                "width": layer.width(),
                "height": layer.height(),
                "band_count": layer.bandCount(),
                "extent": {
                    "xMin": extent.xMinimum(),
                    "yMin": extent.yMinimum(),
                    "xMax": extent.xMaximum(),
                    "yMax": extent.yMaximum(),
                },
            })
        return result

    def check_crs_consistency(self, layer_ids=None, **kwargs):
        """Check CRS consistency across selected project layers."""
        project = QgsProject.instance()
        layers = []
        if layer_ids:
            layers = [self._get_layer(layer_id) for layer_id in layer_ids]
        else:
            layers = list(project.mapLayers().values())
        crs_map = {}
        layer_info = []
        for layer in layers:
            authid = layer.crs().authid()
            crs_map.setdefault(authid or "UNKNOWN", []).append(layer.name())
            layer_info.append({"layer_id": layer.id(), "name": layer.name(), "crs": authid})
        return {
            "consistent": len(crs_map) <= 1,
            "crs_groups": crs_map,
            "layers": layer_info,
        }

    def reproject_layer(self, layer_id, target_crs, output_path, **kwargs):
        """Reproject a vector layer to a target CRS and add it to the project."""
        layer = self._get_layer(layer_id, "vector")
        return self._run_file_algorithm("native:reprojectlayer", {
            "INPUT": layer,
            "TARGET_CRS": target_crs,
        }, output_path, layer_name=f"{layer.name()}_reprojected")

    def clip_vector(self, input_layer_id, overlay_layer_id, output_path, **kwargs):
        """Clip a vector layer by polygon overlay."""
        input_layer = self._get_layer(input_layer_id, "vector")
        overlay_layer = self._get_layer(overlay_layer_id, "vector")
        return self._run_file_algorithm("native:clip", {
            "INPUT": input_layer,
            "OVERLAY": overlay_layer,
        }, output_path, layer_name=f"{input_layer.name()}_clip")

    def intersection(self, input_layer_id, overlay_layer_id, output_path, input_fields=None, overlay_fields=None, **kwargs):
        """Intersect two vector layers and preserve selected attributes."""
        input_layer = self._get_layer(input_layer_id, "vector")
        overlay_layer = self._get_layer(overlay_layer_id, "vector")
        return self._run_file_algorithm("native:intersection", {
            "INPUT": input_layer,
            "OVERLAY": overlay_layer,
            "INPUT_FIELDS": input_fields or [],
            "OVERLAY_FIELDS": overlay_fields or [],
            "OVERLAY_FIELDS_PREFIX": "ov_",
        }, output_path, layer_name=f"{input_layer.name()}_intersection")

    def difference(self, input_layer_id, overlay_layer_id, output_path, **kwargs):
        """Erase overlay geometry from input vector layer."""
        input_layer = self._get_layer(input_layer_id, "vector")
        overlay_layer = self._get_layer(overlay_layer_id, "vector")
        return self._run_file_algorithm("native:difference", {
            "INPUT": input_layer,
            "OVERLAY": overlay_layer,
        }, output_path, layer_name=f"{input_layer.name()}_difference")

    def join_attributes_by_location(self, input_layer_id, join_layer_id, output_path, predicate=None, join_fields=None, method=0, discard_nonmatching=False, prefix="join_", **kwargs):
        """Spatially join attributes from one vector layer to another."""
        input_layer = self._get_layer(input_layer_id, "vector")
        join_layer = self._get_layer(join_layer_id, "vector")
        return self._run_file_algorithm("native:joinattributesbylocation", {
            "INPUT": input_layer,
            "JOIN": join_layer,
            "PREDICATE": predicate or [0],
            "JOIN_FIELDS": join_fields or [],
            "METHOD": method,
            "DISCARD_NONMATCHING": discard_nonmatching,
            "PREFIX": prefix,
        }, output_path, layer_name=f"{input_layer.name()}_spatial_join")

    def calculate_area_fields(self, layer_id, area_field="area_m2", hectare_field="area_ha", precision=2, **kwargs):
        """Add/update area fields on a polygon layer in-place."""
        layer = self._get_layer(layer_id, "vector")
        backup_path = backup_source(layer)
        if not backup_path:
            QgsMessageLog.logMessage("WARNING: Could not create backup before area calculation", "Astyyym QGIS MCP", _msg_level("Warning"))
        existing = [field.name() for field in layer.fields()]
        from qgis.core import QgsField, QgsDistanceArea
        from qgis.PyQt.QtCore import QVariant
        new_fields = []
        if area_field not in existing:
            new_fields.append(QgsField(area_field, QVariant.Double))
        if hectare_field and hectare_field not in existing:
            new_fields.append(QgsField(hectare_field, QVariant.Double))
        if new_fields:
            layer.dataProvider().addAttributes(new_fields)
            layer.updateFields()
        area_idx = layer.fields().indexOf(area_field)
        hectare_idx = layer.fields().indexOf(hectare_field) if hectare_field else -1
        distance_area = QgsDistanceArea()
        distance_area.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
        distance_area.setEllipsoid(QgsProject.instance().ellipsoid() or "WGS84")
        layer.startEditing()
        count = 0
        for feature in layer.getFeatures():
            geom = feature.geometry()
            if not geom or geom.isEmpty():
                continue
            area_m2 = round(distance_area.measureArea(geom), precision)
            layer.changeAttributeValue(feature.id(), area_idx, area_m2)
            if hectare_idx >= 0:
                layer.changeAttributeValue(feature.id(), hectare_idx, round(area_m2 / 10000.0, precision))
            count += 1
        layer.commitChanges()
        return {"layer_id": layer_id, "area_field": area_field, "hectare_field": hectare_field, "features_updated": count, "backup": backup_path}

    def summarize_area_by_zone(self, layer_id, group_field, area_field=None, **kwargs):
        """Summarize polygon area by an attribute field."""
        layer = self._get_layer(layer_id, "vector")
        field_names = [field.name() for field in layer.fields()]
        if group_field not in field_names:
            # Try case-insensitive fallback
            match = [f for f in field_names if f.lower() == group_field.lower()]
            if match:
                group_field = match[0]
            else:
                preview = field_names[:15]
                more = f" ... and {len(field_names)-15} more" if len(field_names) > 15 else ""
                raise Exception(
                    f"Group field not found: '{group_field}'. "
                    f"Available fields ({len(field_names)}): {preview}{more}"
                )
        from qgis.core import QgsDistanceArea
        distance_area = QgsDistanceArea()
        distance_area.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
        distance_area.setEllipsoid(QgsProject.instance().ellipsoid() or "WGS84")
        summary = {}
        total_area = 0.0
        for feature in layer.getFeatures():
            key = str(feature.attribute(group_field))
            if area_field:
                # if area_field not in field_names, try case-insensitive match
                if area_field not in field_names:
                    amatch = [f for f in field_names if f.lower() == area_field.lower()]
                    if amatch:
                        area_field = amatch[0]
                    else:
                        area_field = None  # no match at all → fall through to geometry calc
            if area_field:
                area = float(feature.attribute(area_field) or 0)
            else:
                geom = feature.geometry()
                area = distance_area.measureArea(geom) if geom and not geom.isEmpty() else 0.0
            item = summary.setdefault(key, {"feature_count": 0, "area_m2": 0.0, "area_ha": 0.0, "percent": 0.0})
            item["feature_count"] += 1
            item["area_m2"] += area
            total_area += area
        for item in summary.values():
            item["area_m2"] = round(item["area_m2"], 2)
            item["area_ha"] = round(item["area_m2"] / 10000.0, 4)
            item["percent"] = round(item["area_m2"] / total_area * 100, 2) if total_area else 0.0
        return {"layer_id": layer_id, "group_field": group_field, "total_area_m2": round(total_area, 2), "groups": summary}

    def select_by_expression(self, layer_id, expression, method=0, **kwargs):
        """Select features by QGIS expression."""
        layer = self._get_layer(layer_id, "vector")
        from qgis.core import QgsExpression, QgsFeatureRequest, QgsVectorLayer
        expr = QgsExpression(expression)
        if expr.hasParserError():
            raise Exception(f"Expression error: {expr.parserError()}")
        ids = [feature.id() for feature in layer.getFeatures(QgsFeatureRequest(expr))]
        # QGIS 4 (PyQt6): selectByIds 2nd arg must be SelectBehavior enum, not bare int
        behavior_map = {
            0: QgsVectorLayer.SelectBehavior.SetSelection,
            1: QgsVectorLayer.SelectBehavior.AddToSelection,
            2: QgsVectorLayer.SelectBehavior.IntersectSelection,
            3: QgsVectorLayer.SelectBehavior.RemoveFromSelection,
        }
        behavior = behavior_map.get(method, QgsVectorLayer.SelectBehavior.SetSelection)
        layer.selectByIds(ids, behavior)
        return {"layer_id": layer_id, "expression": expression, "selected_count": len(ids), "selected_ids_sample": ids[:50]}

    def export_selected_features(self, layer_id, output_path, **kwargs):
        """Export currently selected vector features to a file."""
        layer = self._get_layer(layer_id, "vector")
        if layer.selectedFeatureCount() == 0:
            raise Exception("No selected features to export")
        import os
        from qgis.core import QgsVectorFileWriter
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.fileEncoding = "UTF-8"
        options.onlySelectedFeatures = True
        err, err_msg, out_path, out_name = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer, output_path, QgsProject.instance().transformContext(), options
        )
        if err != QgsVectorFileWriter.WriterError.NoError:
            raise Exception(f"Selected export failed: {err_msg}")
        new_id = add_to_project(output_path)
        return {"output": output_path, "selected_count": layer.selectedFeatureCount(), "layer_id": new_id}

    def clip_raster_by_mask(self, raster_layer_id, mask_layer_id, output_path, crop_to_cutline=True, alpha_band=True, **kwargs):
        """Clip raster by vector mask and add result to project."""
        raster_layer = self._get_layer(raster_layer_id, "raster")
        mask_layer = self._get_layer(mask_layer_id, "vector")
        return self._run_file_algorithm("gdal:cliprasterbymasklayer", {
            "INPUT": raster_layer,
            "MASK": mask_layer,
            "CROP_TO_CUTLINE": crop_to_cutline,
            "ALPHA_BAND": alpha_band,
        }, output_path, layer_name=f"{raster_layer.name()}_clip")

    def zonal_statistics(self, raster_layer_id, zone_layer_id, output_path, prefix="z_", statistics=None, **kwargs):
        """Calculate raster statistics for polygon zones into a new vector file."""
        zones = self._get_layer(zone_layer_id, "vector")
        raster = self._get_layer(raster_layer_id, "raster")
        stats = statistics if statistics is not None else [2, 3, 5, 6]
        return self._run_file_algorithm("native:zonalstatisticsfb", {
            "INPUT": zones,
            "INPUT_RASTER": raster,
            "RASTER_BAND": 1,
            "COLUMN_PREFIX": prefix,
            "STATISTICS": stats,
        }, output_path, layer_name=f"{zones.name()}_zonal_stats")


    def cad_to_gpkg(self, cad_path, output_path, **kwargs):
        """Convert CAD file (DXF/DWG) to GeoPackage."""
        import os
        from qgis.core import QgsVectorLayer, QgsVectorFileWriter, QgsProject, QgsCoordinateTransformContext

        if not os.path.exists(cad_path):
            raise Exception(f"CAD file not found: {cad_path}")

        ext = os.path.splitext(cad_path)[1].lower()
        if ext not in (".dxf", ".dwg"):
            raise Exception(f"Unsupported format '{ext}'. Expected .dxf or .dwg")

        # Load CAD via OGR — QGIS natively supports DXF/DWG
        layer = QgsVectorLayer(cad_path, "cad_source", "ogr")
        if not layer.isValid():
            raise Exception(
                f"Failed to load CAD file: {cad_path}. "
                "Check that the file is a valid DXF/DWG."
            )

        # Export to GPKG
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.fileEncoding = "UTF-8"

        write_result = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer, output_path, QgsProject.instance().transformContext(), options
        )
        err, err_msg, out_path, out_name = write_result

        if err != QgsVectorFileWriter.WriterError.NoError:
            raise Exception(f"GPKG export failed: {err_msg}")

        new_id = add_to_project(output_path)

        return {
            "cad_path": cad_path,
            "output": output_path,
            "layer_id": new_id,
            "feature_count": layer.featureCount(),
            "crs": layer.crs().authid() if layer.crs().isValid() else "unknown",
        }

    # ── 测绘/规划扩展 handlers ──

    def slope(self, raster_layer_id, output_path, **kwargs):
        """Calculate slope from a DEM raster (in degrees)."""
        raster = self._get_layer(raster_layer_id, "raster")
        return self._run_file_algorithm("gdal:slope", {
            "INPUT": raster,
        }, output_path, layer_name=f"{raster.name()}_slope")

    def aspect(self, raster_layer_id, output_path, **kwargs):
        """Calculate aspect (slope direction) from a DEM raster."""
        raster = self._get_layer(raster_layer_id, "raster")
        return self._run_file_algorithm("gdal:aspect", {
            "INPUT": raster,
        }, output_path, layer_name=f"{raster.name()}_aspect")

    def contour(self, raster_layer_id, output_path, interval=100, **kwargs):
        """Generate contour lines from a DEM raster."""
        raster = self._get_layer(raster_layer_id, "raster")
        import os
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        import processing
        result = processing.run("gdal:contour", {
            "INPUT": raster,
            "BAND": 1,
            "INTERVAL": interval,
            "OUTPUT": output_path,
        })
        new_id = add_to_project(output_path)
        return {
            "algorithm": "gdal:contour",
            "output": output_path,
            "layer_id": new_id,
            "interval": interval,
        }

    def create_grid(self, output_path, extent_layer_id=None, spacing=1000, **kwargs):
        """Create a rectangular grid (fishnet) over a layer's extent."""
        import os
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        import processing
        from qgis.core import QgsProject
        params = {
            "TYPE": 2,  # Rectangle (polygon)
            "CRS": QgsProject.instance().crs(),
            "OUTPUT": output_path,
        }
        if extent_layer_id:
            layer = self._get_layer(extent_layer_id)
            extent = layer.extent()
            params["EXTENT"] = extent
            params["HSPACING"] = spacing
            params["VSPACING"] = spacing
        else:
            raise Exception("extent_layer_id is required for grid creation")
        result = processing.run("native:creategrid", params)
        new_id = add_to_project(output_path)
        return {
            "algorithm": "native:creategrid",
            "output": output_path,
            "layer_id": new_id,
            "spacing": spacing,
        }

    def idw_interpolation(self, point_layer_id, value_field, output_path, pixel_size=100, **kwargs):
        """IDW interpolation from point data to raster."""
        point_layer = self._get_layer(point_layer_id, "vector")
        # Convert field name to index (QGIS IDW expects numeric index)
        field_names = [f.name() for f in point_layer.fields()]
        if value_field in field_names:
            field_idx = field_names.index(value_field)
        else:
            try:
                field_idx = int(value_field)
            except ValueError:
                raise Exception(f"Field '{value_field}' not found. Available: {field_names}")
        import os
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        import processing
        extent = point_layer.extent()
        result = processing.run("qgis:idwinterpolation", {
            "INTERPOLATION_DATA": f"{point_layer.source()}::~::0::~::{field_idx}::~::0",
            "PIXEL_SIZE": pixel_size,
            "EXTENT": f"{extent.xMinimum()},{extent.xMaximum()},{extent.yMinimum()},{extent.yMaximum()}",
            "OUTPUT": output_path,
        })
        new_id = add_to_project(output_path)
        return {
            "algorithm": "qgis:idwinterpolation",
            "output": output_path,
            "layer_id": new_id,
            "value_field": value_field,
        }

    def cut_fill(self, dem_layer_id, design_surface_layer_id, output_path, **kwargs):
        """Calculate cut/fill by subtracting design surface from DEM.
        Positive = cut (remove), Negative = fill (add)."""
        dem = self._get_layer(dem_layer_id, "raster")
        design = self._get_layer(design_surface_layer_id, "raster")
        import os
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        import processing
        from qgis.core import QgsRasterLayer
        # QGIS 4 uses "native:rastercalc" (not "native:rastercalculator")
        result = processing.run("native:rastercalc", {
            "LAYERS": [dem, design],
            "EXPRESSION": f'"{dem.name()}@1" - "{design.name()}@1"',
            "OUTPUT": output_path,
        })
        new_id = add_to_project(output_path)
        return {
            "algorithm": "native:rastercalculator",
            "output": output_path,
            "layer_id": new_id,
            "note": "Positive values = cut (dem higher than design), Negative = fill",
        }


    # ------------------------------------------------------------------
    # Project structure, controlled editing, and delivery diagnostics
    # ------------------------------------------------------------------

    def _record_operation(self, command, params, status, started_at, result):
        """Retain a bounded, JSON-safe audit trail for MCP commands."""
        def compact(value, limit=1000):
            try:
                text = json.dumps(value, default=str, ensure_ascii=False)
            except Exception:
                text = repr(value)
            return text if len(text) <= limit else text[:limit] + "..."

        entry = {
            "timestamp": started_at,
            "command": command,
            "status": status,
            "params": compact(params, 600),
            "result": compact(result),
        }
        self.operation_log.append(entry)
        if len(self.operation_log) > self.operation_log_limit:
            del self.operation_log[:-self.operation_log_limit]

    def _extent_dict(self, extent):
        return {
            "x_min": extent.xMinimum(), "y_min": extent.yMinimum(),
            "x_max": extent.xMaximum(), "y_max": extent.yMaximum(),
        }

    def _safe_value(self, value):
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        try:
            return value.toString()
        except Exception:
            return str(value)

    def _field_schema(self, layer):
        return [
            {
                "name": field.name(),
                "type": field.typeName(),
                "length": field.length(),
                "precision": field.precision(),
            }
            for field in layer.fields()
        ]

    def _validate_expression_for_layer(self, layer, expression):
        expression = (expression or "").strip()
        if not expression:
            return None, {"valid": True, "expression": "", "message": "No filter supplied; all features match."}
        expr = QgsExpression(expression)
        if expr.hasParserError():
            return None, {"valid": False, "expression": expression, "error": expr.parserErrorString()}
        referenced = set(expr.referencedColumns())
        known = {field.name() for field in layer.fields()}
        missing = sorted(referenced - known)
        if missing:
            return None, {
                "valid": False, "expression": expression,
                "error": f"Unknown field references: {missing}",
                "missing_fields": missing,
            }
        context = QgsProject.instance().createExpressionContext()
        context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
        return expr, {"valid": True, "expression": expression}

    def _matching_feature_ids(self, layer, expression=None, feature_ids=None):
        if feature_ids is not None:
            known = {feature.id() for feature in layer.getFeatures()}
            requested = [int(fid) for fid in feature_ids]
            missing = [fid for fid in requested if fid not in known]
            if missing:
                raise Exception(f"Feature IDs not found: {missing[:20]}")
            return requested, {"valid": True, "expression": None}
        expr, validation = self._validate_expression_for_layer(layer, expression)
        if not validation["valid"]:
            raise Exception(f"Invalid expression: {validation['error']}")
        request = QgsFeatureRequest(expr) if expr else QgsFeatureRequest()
        return [feature.id() for feature in layer.getFeatures(request)], validation

    def _feature_payload(self, feature, field_names):
        return {
            "id": feature.id(),
            "attributes": {name: self._safe_value(feature[name]) for name in field_names},
            "has_geometry": bool(feature.hasGeometry() and not feature.geometry().isEmpty()),
        }

    def _layer_tree_node(self, node):
        if isinstance(node, QgsLayerTreeGroup):
            return {
                "kind": "group", "name": node.name(), "visible": node.isVisible(),
                "children": [self._layer_tree_node(child) for child in node.children()],
            }
        if isinstance(node, QgsLayerTreeLayer):
            layer = node.layer()
            return {
                "kind": "layer", "id": layer.id() if layer else None,
                "name": layer.name() if layer else node.name(),
                "visible": node.isVisible(),
                "valid": bool(layer and layer.isValid()),
                "type": self._get_layer_type(layer) if layer else "missing",
            }
        return {"kind": "unknown", "name": node.name()}

    def _project_variables(self, project):
        try:
            scope = QgsExpressionContextUtils.projectScope(project)
            return {name: self._safe_value(scope.variable(name)) for name in scope.variableNames()}
        except Exception:
            return {}

    def inspect_project_state(self, **kwargs):
        """Return the project structure and current state without modifying it."""
        project = QgsProject.instance()
        layouts = []
        try:
            layouts = [layout.name() for layout in project.layoutManager().printLayouts()]
        except Exception:
            pass
        extent = self.iface.mapCanvas().extent() if self.iface else None
        return {
            "filename": project.fileName(), "title": project.title(),
            "crs": project.crs().authid(), "is_dirty": project.isDirty(),
            "layer_count": len(project.mapLayers()), "layer_tree": self.get_layer_tree()["tree"],
            "layouts": layouts, "project_variables": self._project_variables(project),
            "canvas_extent": self._extent_dict(extent) if extent else None,
        }

    def get_layer_tree(self, **kwargs):
        """Return QGIS' actual layer/group hierarchy and visibility state."""
        return {"tree": self._layer_tree_node(QgsProject.instance().layerTreeRoot())}

    def inspect_layer(self, layer_id, **kwargs):
        """Return structured metadata for a vector or raster layer."""
        layer = self._get_layer(layer_id)
        root = QgsProject.instance().layerTreeRoot()
        tree_layer = root.findLayer(layer_id)
        result = {
            "layer_id": layer.id(), "name": layer.name(), "valid": layer.isValid(),
            "type": self._get_layer_type(layer), "provider": layer.providerType(),
            "source": layer.source(), "crs": layer.crs().authid(),
            "extent": self._extent_dict(layer.extent()),
            "visible": bool(tree_layer and tree_layer.isVisible()),
            "group": self._get_group_path(tree_layer) if tree_layer else "",
        }
        if _is_vector_layer(layer):
            result.update({
                "geometry_type": _geometry_type_str_from_layer(layer),
                "feature_count": layer.featureCount(), "fields": self._field_schema(layer),
                "selected_count": layer.selectedFeatureCount(), "is_editable": layer.isEditable(),
            })
        elif _is_raster_layer(layer):
            result.update({"width": layer.width(), "height": layer.height(), "band_count": layer.bandCount()})
        return result

    def get_project_diagnostics(self, **kwargs):
        """Summarize project-level data, CRS, and unsaved-edit risks."""
        project = QgsProject.instance()
        invalid_layers, empty_layers, editable_layers = [], [], []
        for layer in project.mapLayers().values():
            if not layer.isValid():
                invalid_layers.append({"layer_id": layer.id(), "name": layer.name(), "source": layer.source()})
                continue
            if _is_vector_layer(layer):
                if layer.featureCount() == 0:
                    empty_layers.append({"layer_id": layer.id(), "name": layer.name()})
                if layer.isEditable():
                    editable_layers.append({"layer_id": layer.id(), "name": layer.name()})
        crs = self.check_crs_consistency()
        return {
            "project_file": project.fileName(), "project_is_dirty": project.isDirty(),
            "invalid_layers": invalid_layers, "empty_vector_layers": empty_layers,
            "editable_layers": editable_layers, "crs_consistency": crs,
            "ok": not invalid_layers and not editable_layers,
        }

    def query_features(self, layer_id, expression=None, fields=None, limit=100, selected_only=False, **kwargs):
        """Read vector attributes after optional expression or selection filtering."""
        layer = self._get_layer(layer_id, "vector")
        if limit < 1 or limit > 1000:
            raise Exception("limit must be between 1 and 1000")
        field_names = fields or [field.name() for field in layer.fields()]
        unknown = sorted(set(field_names) - {field.name() for field in layer.fields()})
        if unknown:
            raise Exception(f"Unknown fields: {unknown}")
        if selected_only:
            request = QgsFeatureRequest().setFilterFids(layer.selectedFeatureIds())
            validation = {"valid": True, "expression": None, "selected_only": True}
        else:
            expr, validation = self._validate_expression_for_layer(layer, expression)
            if not validation["valid"]:
                return {"layer_id": layer_id, "features": [], "matched_count": 0, "validation": validation}
            request = QgsFeatureRequest(expr) if expr else QgsFeatureRequest()
        features = []
        for feature in layer.getFeatures(request):
            features.append(self._feature_payload(feature, field_names))
            if len(features) >= limit:
                break
        return {"layer_id": layer_id, "fields": field_names, "features": features, "returned_count": len(features), "validation": validation}

    def get_layer_statistics(self, layer_id, fields=None, expression=None, **kwargs):
        """Calculate concise attribute statistics for matching vector features."""
        layer = self._get_layer(layer_id, "vector")
        field_names = fields or [field.name() for field in layer.fields()]
        unknown = sorted(set(field_names) - {field.name() for field in layer.fields()})
        if unknown:
            raise Exception(f"Unknown fields: {unknown}")
        expr, validation = self._validate_expression_for_layer(layer, expression)
        if not validation["valid"]:
            return {"layer_id": layer_id, "validation": validation, "feature_count": 0, "fields": {}}
        values = {name: [] for name in field_names}
        request = QgsFeatureRequest(expr) if expr else QgsFeatureRequest()
        feature_count = 0
        for feature in layer.getFeatures(request):
            feature_count += 1
            for name in field_names:
                values[name].append(feature[name])
        stats = {}
        for name, field_values in values.items():
            present = [value for value in field_values if value is not None]
            numeric = [float(value) for value in present if isinstance(value, (int, float)) and not isinstance(value, bool)]
            item = {"null_count": len(field_values) - len(present), "unique_count": len({str(value) for value in present})}
            if numeric:
                item.update({"min": min(numeric), "max": max(numeric), "mean": sum(numeric) / len(numeric)})
            stats[name] = item
        return {"layer_id": layer_id, "feature_count": feature_count, "fields": stats, "validation": validation}

    def validate_expression(self, layer_id, expression, **kwargs):
        """Parse a QGIS expression and report its matching feature count without writing."""
        layer = self._get_layer(layer_id, "vector")
        expr, validation = self._validate_expression_for_layer(layer, expression)
        if not validation["valid"]:
            return {"layer_id": layer_id, **validation, "matched_count": 0}
        request = QgsFeatureRequest(expr) if expr else QgsFeatureRequest()
        return {"layer_id": layer_id, **validation, "matched_count": sum(1 for _ in layer.getFeatures(request))}

    def manage_selection(self, layer_id, operation="get", expression=None, feature_ids=None, **kwargs):
        """Read or change QGIS' in-memory selection; this never writes the data source."""
        layer = self._get_layer(layer_id, "vector")
        operation = operation.lower()
        if operation == "get":
            return {"layer_id": layer_id, "selected_ids": list(layer.selectedFeatureIds()), "selected_count": layer.selectedFeatureCount()}
        if operation == "clear":
            layer.removeSelection()
            return {"layer_id": layer_id, "operation": operation, "selected_count": 0}
        ids, validation = self._matching_feature_ids(layer, expression, feature_ids)
        behavior_map = {
            "set": QgsVectorLayer.SelectBehavior.SetSelection,
            "add": QgsVectorLayer.SelectBehavior.AddToSelection,
            "remove": QgsVectorLayer.SelectBehavior.RemoveFromSelection,
            "intersect": QgsVectorLayer.SelectBehavior.IntersectSelection,
        }
        if operation not in behavior_map:
            raise Exception("operation must be get, clear, set, add, remove, or intersect")
        layer.selectByIds(ids, behavior_map[operation])
        return {"layer_id": layer_id, "operation": operation, "matched_count": len(ids), "selected_count": layer.selectedFeatureCount(), "validation": validation}

    def _run_short_edit(self, layer, operation, ids, dry_run, apply_change):
        summary = {"layer_id": layer.id(), "layer_name": layer.name(), "operation": operation, "affected_count": len(ids), "dry_run": dry_run}
        if dry_run:
            return summary
        if layer.isEditable():
            raise Exception("Layer is already in an edit session; finish or roll back it before MCP writes.")
        backup_path = backup_source(layer)
        if not layer.startEditing():
            raise Exception(f"Could not start edit session: {layer.commitErrors()}")
        layer.beginEditCommand(operation)
        try:
            apply_change()
            layer.endEditCommand()
            if not layer.commitChanges():
                errors = layer.commitErrors()
                layer.rollBack()
                raise Exception(f"Commit failed and was rolled back: {errors}")
        except Exception:
            try:
                layer.destroyEditCommand()
            except Exception:
                pass
            layer.rollBack()
            raise
        summary["backup_path"] = backup_path
        summary["committed"] = True
        return summary

    def calculate_field(self, layer_id, field_name, expression, filter_expression=None, dry_run=True, **kwargs):
        """Calculate an existing field for matching features in a short, guarded edit transaction."""
        layer = self._get_layer(layer_id, "vector")
        if field_name not in {field.name() for field in layer.fields()}:
            raise Exception(f"Field does not exist: {field_name}. Add it explicitly before calculating values.")
        expr = QgsExpression(expression)
        if expr.hasParserError():
            raise Exception(f"Invalid calculation expression: {expr.parserErrorString()}")
        ids, validation = self._matching_feature_ids(layer, filter_expression)
        field_index = layer.fields().indexOf(field_name)
        context = QgsProject.instance().createExpressionContext()
        context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
        def apply_change():
            for feature in layer.getFeatures(QgsFeatureRequest().setFilterFids(ids)):
                context.setFeature(feature)
                value = expr.evaluate(context)
                if expr.hasEvalError():
                    raise Exception(f"Expression evaluation failed for feature {feature.id()}: {expr.evalErrorString()}")
                if not layer.changeAttributeValue(feature.id(), field_index, value):
                    raise Exception(f"Could not update feature {feature.id()}")
        result = self._run_short_edit(layer, "calculate_field", ids, dry_run, apply_change)
        result.update({"field_name": field_name, "expression": expression, "validation": validation})
        return result

    def update_feature_attributes(self, layer_id, changes, expression=None, feature_ids=None, dry_run=True, **kwargs):
        """Set named attribute values for selected matching features; geometry writes are intentionally excluded."""
        layer = self._get_layer(layer_id, "vector")
        if not isinstance(changes, dict) or not changes:
            raise Exception("changes must be a non-empty object mapping field names to values")
        indexes = {name: layer.fields().indexOf(name) for name in changes}
        unknown = [name for name, index in indexes.items() if index < 0]
        if unknown:
            raise Exception(f"Unknown fields: {unknown}")
        if expression is None and feature_ids is None:
            raise Exception("Provide expression or feature_ids for attribute updates; use an explicit expression such as '1=1' to target every feature.")
        ids, validation = self._matching_feature_ids(layer, expression, feature_ids)
        def apply_change():
            for fid in ids:
                for name, value in changes.items():
                    if not layer.changeAttributeValue(fid, indexes[name], value):
                        raise Exception(f"Could not update {name} for feature {fid}")
        result = self._run_short_edit(layer, "update_feature_attributes", ids, dry_run, apply_change)
        result.update({"changed_fields": sorted(changes), "validation": validation})
        return result

    def delete_features(self, layer_id, expression=None, feature_ids=None, dry_run=True, **kwargs):
        """Delete explicitly matched vector features in a guarded short transaction."""
        layer = self._get_layer(layer_id, "vector")
        if expression is None and feature_ids is None:
            raise Exception("Provide expression or feature_ids for deletion; use an explicit expression such as '1=1' to target every feature.")
        ids, validation = self._matching_feature_ids(layer, expression, feature_ids)
        if not ids:
            return {"layer_id": layer_id, "operation": "delete_features", "affected_count": 0, "dry_run": dry_run, "validation": validation}
        def apply_change():
            if not layer.deleteFeatures(ids):
                raise Exception("QGIS refused to delete one or more features")
        result = self._run_short_edit(layer, "delete_features", ids, dry_run, apply_change)
        result["validation"] = validation
        return result

    def validate_project_for_delivery(self, **kwargs):
        """Check whether the current project has save, source, CRS, or edit-state blockers."""
        project = QgsProject.instance()
        diagnostics = self.get_project_diagnostics()
        project_path = project.fileName()
        issues = []
        if not project_path:
            issues.append({"severity": "error", "code": "unsaved_project", "message": "Project has no file path."})
        elif not os.path.isfile(project_path):
            issues.append({"severity": "error", "code": "missing_project_file", "message": project_path})
        if diagnostics["project_is_dirty"]:
            issues.append({"severity": "warning", "code": "unsaved_changes", "message": "Project has unsaved changes."})
        for item in diagnostics["invalid_layers"]:
            issues.append({"severity": "error", "code": "invalid_layer", **item})
        for item in diagnostics["editable_layers"]:
            issues.append({"severity": "warning", "code": "active_edit_session", **item})
        if not diagnostics["crs_consistency"]["consistent"]:
            issues.append({"severity": "warning", "code": "mixed_crs", "details": diagnostics["crs_consistency"]["crs_groups"]})
        return {"project_file": project_path, "ready": not any(item["severity"] == "error" for item in issues), "issues": issues, "diagnostics": diagnostics}

    def verify_output_file(self, path, expected_type=None, **kwargs):
        """Check that an output file exists and can be reopened by QGIS."""
        if not path or not os.path.isfile(path):
            return {"path": path, "exists": False, "valid": False, "error": "File does not exist."}
        suffix = os.path.splitext(path)[1].lower()
        if expected_type == "project" or suffix in {".qgs", ".qgz"}:
            temporary_project = QgsProject()
            can_read = temporary_project.read(path)
            return {
                "path": path, "exists": True, "valid": bool(can_read), "type": "project",
                "layer_count": len(temporary_project.mapLayers()) if can_read else 0,
                "error": "QGIS could not read the project file." if not can_read else None,
            }
        vector = QgsVectorLayer(path, "verification", "ogr")
        if vector.isValid():
            return {"path": path, "exists": True, "valid": True, "type": "vector", "feature_count": vector.featureCount(), "crs": vector.crs().authid(), "fields": self._field_schema(vector)}
        raster = QgsRasterLayer(path, "verification")
        if raster.isValid():
            return {"path": path, "exists": True, "valid": True, "type": "raster", "width": raster.width(), "height": raster.height(), "band_count": raster.bandCount(), "crs": raster.crs().authid()}
        return {"path": path, "exists": True, "valid": False, "error": "QGIS could not load this file as vector or raster."}

    def validate_processing_result(self, layer_id=None, output_path=None, expectations=None, **kwargs):
        """Validate an existing result layer or output path against simple expectations."""
        expectations = expectations or {}
        result = self.inspect_layer(layer_id) if layer_id else self.verify_output_file(output_path)
        checks = []
        for key in ("type", "crs", "feature_count", "min_feature_count"):
            if key not in expectations:
                continue
            actual = result.get("feature_count") if key == "min_feature_count" else result.get(key)
            expected = expectations[key]
            if key == "min_feature_count" and actual is not None:
                passed = actual >= expected
            elif key == "type" and expected in {"vector", "raster"}:
                passed = actual == expected or str(actual).startswith(expected + "_")
            else:
                passed = actual == expected
            checks.append({"key": key, "expected": expected, "actual": actual, "passed": passed})
        return {"target": layer_id or output_path, "valid": bool(result.get("valid", True)), "checks": checks, "passed": bool(result.get("valid", True)) and all(check["passed"] for check in checks), "details": result}

    def get_operation_log(self, limit=50, **kwargs):
        """Return the bounded audit trail for commands handled by this plugin instance."""
        if limit < 1 or limit > self.operation_log_limit:
            raise Exception(f"limit must be between 1 and {self.operation_log_limit}")
        return {"entries": self.operation_log[-limit:], "entry_count": len(self.operation_log)}

    def capture_project_state(self, **kwargs):
        """Return a timestamped, read-only project snapshot suitable for before/after comparison."""
        state = self.inspect_project_state()
        state["captured_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        state["diagnostics"] = self.get_project_diagnostics()
        return state


class QgisMCPDockWidget(QDockWidget):
    """Dock widget for the QGIS MCP plugin"""
    closed = pyqtSignal()

    def __init__(self, iface):
        super().__init__("Astyyym QGIS MCP")
        self.iface = iface
        self.server = None
        self.setup_ui()

    def setup_ui(self):
        """Set up the dock widget UI"""
        # Create widget and layout
        widget = QWidget()
        layout = QVBoxLayout()
        widget.setLayout(layout)

        # Add port selection
        layout.addWidget(QLabel("Server Port:"))
        self.port_spin = QSpinBox()
        self.port_spin.setMinimum(1024)
        self.port_spin.setMaximum(65535)
        self.port_spin.setValue(9877)
        layout.addWidget(self.port_spin)

        # Add server control buttons
        self.start_button = QPushButton("Start Server")
        self.start_button.clicked.connect(self.start_server)
        layout.addWidget(self.start_button)

        self.stop_button = QPushButton("Stop Server")
        self.stop_button.clicked.connect(self.stop_server)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)

        # Add status label
        self.status_label = QLabel("Server: Stopped")
        layout.addWidget(self.status_label)

        # Add to dock widget
        self.setWidget(widget)

    def start_server(self):
        """Start the server"""
        if not self.server:
            port = self.port_spin.value()
            self.server = QgisMCPServer(port=port, iface=self.iface)

        if self.server.start():
            self.status_label.setText(f"Server: Running on port {self.server.port}")
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.port_spin.setEnabled(False)

    def stop_server(self):
        """Stop the server"""
        if self.server:
            self.server.stop()
            self.server = None

        self.status_label.setText("Server: Stopped")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.port_spin.setEnabled(True)

    def closeEvent(self, event):
        """Stop server on dock close"""
        self.stop_server()
        self.closed.emit()
        super().closeEvent(event)


class QgisMCPPlugin:
    """Main plugin class for QGIS MCP"""

    def __init__(self, iface):
        self.iface = iface
        self.dock_widget = None
        self.action = None

    def initGui(self):
        """Initialize GUI"""
        # Create action with icon
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        self.action = QAction(
            QIcon(icon_path) if os.path.exists(icon_path) else QIcon(),
            "Astyyym QGIS MCP",
            self.iface.mainWindow()
        )
        self.action.setCheckable(True)
        self.action.triggered.connect(self.toggle_dock)

        # Add to plugins menu and toolbar
        self.iface.addPluginToMenu("Astyyym QGIS MCP", self.action)
        self.iface.addToolBarIcon(self.action)

    def toggle_dock(self, checked):
        """Toggle the dock widget"""
        if checked:
            # Create dock widget if it doesn't exist
            if not self.dock_widget:
                self.dock_widget = QgisMCPDockWidget(self.iface)
                self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_widget)
                # Connect close event
                self.dock_widget.closed.connect(self.dock_closed)
            else:
                # Show existing dock widget
                self.dock_widget.show()
        else:
            # Hide dock widget
            if self.dock_widget:
                self.dock_widget.hide()

    def dock_closed(self):
        """Handle dock widget closed"""
        self.action.setChecked(False)

    def unload(self):
        """Unload plugin"""
        # Stop server if running
        if self.dock_widget:
            self.dock_widget.stop_server()
            self.iface.removeDockWidget(self.dock_widget)
            self.dock_widget = None

        # Remove plugin menu item and toolbar icon
        self.iface.removePluginMenu("Astyyym QGIS MCP", self.action)
        self.iface.removeToolBarIcon(self.action)


# Plugin entry point
def classFactory(iface):
    return QgisMCPPlugin(iface)
