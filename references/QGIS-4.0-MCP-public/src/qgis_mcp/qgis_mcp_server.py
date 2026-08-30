#!/usr/bin/env python3
"""
QGIS MCP Client - Simple client to connect to the QGIS MCP server
"""

import logging
from contextlib import asynccontextmanager
import os
import socket
import json
import sys
from typing import AsyncIterator, Dict, Any
from mcp.server.fastmcp import FastMCP, Context

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("QgisMCPServer")

class QgisMCPServer:
    def __init__(self, host='localhost', port=9877):
        self.host = host
        self.port = port
        self.socket = None

    def connect(self):
        """Connect to the QGIS MCP server"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5)  # 5s timeout for recv
            self.socket.connect((self.host, self.port))
            return True
        except Exception as e:
            print(f"Error connecting to server: {str(e)}")
            self.socket = None
            return False

    def disconnect(self):
        """Disconnect from the server"""
        if self.socket:
            self.socket.close()
            self.socket = None

    def send_command(self, command_type, params=None):
        """Send a command to the server and get the response"""
        if not self.socket:
            print("Not connected to server")
            return None

        # Create command
        command = {
            "type": command_type,
            "params": params or {}
        }

        try:
            # Send the command
            self.socket.sendall(json.dumps(command).encode('utf-8'))

            # Receive the response (QGIS plugin uses 4-byte big-endian length prefix)
            # Step 1: read the 4-byte length prefix
            length_data = b''
            while len(length_data) < 4:
                chunk = self.socket.recv(4 - len(length_data))
                if not chunk:
                    raise ConnectionError("Connection closed while reading length prefix")
                length_data += chunk

            payload_length = int.from_bytes(length_data, 'big')

            # Step 2: read the payload
            response_data = b''
            while len(response_data) < payload_length:
                chunk = self.socket.recv(min(4096, payload_length - len(response_data)))
                if not chunk:
                    raise ConnectionError("Connection closed while reading response payload")
                response_data += chunk

            # Parse and return the response
            return json.loads(response_data.decode('utf-8'))

        except Exception as e:
            logger.error(f"Error sending command: {str(e)}")
            self.disconnect()  # 清掉死连接，下次调用自动重连
            return None

_qgis_connection = None

def _get_windows_host_ip():
    """Get the Windows host IP address from WSL's default gateway."""
    import subprocess
    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=5
        )
        parts = result.stdout.strip().split()
        if len(parts) >= 3:
            return parts[2]  # gateway IP is the third field
    except Exception:
        pass
    # Fallback to a well-known WSL2 gateway pattern
    return "172.17.192.1"


def get_qgis_connection():
    """Get or create a persistent Qgis connection"""
    global _qgis_connection

    # If we have an existing connection, check if it's still valid
    if _qgis_connection is not None:
        # send_command 失败后会 disconnect，socket 变 None → 直接走重连
        if _qgis_connection.socket is None:
            _qgis_connection = None
            return get_qgis_connection()
        # Quick check: try a lightweight recv with MSG_PEEK to see if socket is alive
        try:
            _qgis_connection.socket.settimeout(0.001)  # almost instant check
            _qgis_connection.socket.recv(1, socket.MSG_PEEK)
            _qgis_connection.socket.settimeout(5)
            return _qgis_connection
        except socket.timeout:
            # No data waiting = socket is alive (just nothing to read)
            _qgis_connection.socket.settimeout(5)
            return _qgis_connection
        except (socket.error, ConnectionError, OSError) as e:
            # Connection is dead, close it and create a new one
            logger.warning(f"Existing connection is no longer valid: {str(e)}")
            try:
                _qgis_connection.disconnect()
            except Exception:
                pass
            _qgis_connection = None

    # Create a new connection if needed
    if _qgis_connection is None:
        host = os.getenv("QGIS_MCP_HOST", "127.0.0.1")
        port = int(os.getenv("QGIS_MCP_PORT", "9877"))
        import time
        for attempt in range(3):
            _qgis_connection = QgisMCPServer(host=host, port=port)
            if _qgis_connection.connect():
                logger.info("Created new persistent connection to Qgis")
                return _qgis_connection
            _qgis_connection = None
            if attempt < 2:
                logger.warning(f"Connection attempt {attempt+1} failed, retrying in 2s...")
                time.sleep(2)
        logger.error("Failed to connect to Qgis after 3 attempts")
        raise Exception("Could not connect to Qgis. Make sure the Qgis plugin is running.")

    return _qgis_connection

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    # We don't need to create a connection here since we're using the global connection
    # for resources and tools

    try:
        # Just log that we're starting up
        logger.info("QgisMCPServer server starting up")

        # Try to connect to Qgis on startup to verify it's available
        try:
            # This will initialize the global connection if needed
            qgis = get_qgis_connection()
            logger.info("Successfully connected to Qgis on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Qgis on startup: {str(e)}")
            logger.warning("Make sure the Qgis addon is running before using Qgis resources or tools")

        # Return an empty context - we're using the global connection
        yield {}
    finally:
        # Clean up the global connection on shutdown
        global _qgis_connection
        if _qgis_connection:
            logger.info("Disconnecting from Qgis on shutdown")
            _qgis_connection.disconnect()
            _qgis_connection = None
        logger.info("QgisMCPServer server shut down")

mcp = FastMCP(
    "Qgis_mcp",
    instructions="Qgis integration through the Model Context Protocol",
    lifespan=server_lifespan
)

@mcp.tool()
def ping(ctx: Context) -> str:
    """Simple ping command to check server connectivity"""
    qgis = get_qgis_connection()
    result = qgis.send_command("ping")
    return json.dumps(result, indent=2)

@mcp.tool()
def get_qgis_info(ctx: Context) -> str:
    """Get QGIS information"""
    qgis = get_qgis_connection()
    result = qgis.send_command("get_qgis_info")
    return json.dumps(result, indent=2)

@mcp.tool()
def load_project(ctx: Context, path: str) -> str:
    """Load a QGIS project from the specified path."""
    qgis = get_qgis_connection()
    result = qgis.send_command("load_project", {"path": path})
    return json.dumps(result, indent=2)

@mcp.tool()
def create_new_project(ctx: Context, path: str) -> str:
    """Create a new project a save it"""
    qgis = get_qgis_connection()
    result = qgis.send_command("create_new_project", {"path": path})
    return json.dumps(result, indent=2)

@mcp.tool()
def get_project_info(ctx: Context) -> str:
    """Get current project information"""
    qgis = get_qgis_connection()
    result = qgis.send_command("get_project_info")
    return json.dumps(result, indent=2)

@mcp.tool()
def add_vector_layer(ctx: Context, path: str, provider: str = "ogr", name: str = None) -> str:
    """Add a vector layer to the project."""
    qgis = get_qgis_connection()
    params = {"path": path, "provider": provider}
    if name:
        params["name"] = name
    result = qgis.send_command("add_vector_layer", params)
    return json.dumps(result, indent=2)

@mcp.tool()
def add_raster_layer(ctx: Context, path: str, provider: str = "gdal", name: str = None) -> str:
    """Add a raster layer to the project."""
    qgis = get_qgis_connection()
    params = {"path": path, "provider": provider}
    if name:
        params["name"] = name
    result = qgis.send_command("add_raster_layer", params)
    return json.dumps(result, indent=2)

@mcp.tool()
def get_layers(ctx: Context) -> str:
    """Retrieve all layers in the current project."""
    qgis = get_qgis_connection()
    result = qgis.send_command("get_layers")
    return json.dumps(result, indent=2)

@mcp.tool()
def remove_layer(ctx: Context, layer_id: str) -> str:
    """Remove a layer from the project by its ID."""
    qgis = get_qgis_connection()
    result = qgis.send_command("remove_layer", {"layer_id": layer_id})
    return json.dumps(result, indent=2)

@mcp.tool()
def zoom_to_layer(ctx: Context, layer_id: str) -> str:
    """Zoom to the extent of a specified layer."""
    qgis = get_qgis_connection()
    result = qgis.send_command("zoom_to_layer", {"layer_id": layer_id})
    return json.dumps(result, indent=2)

@mcp.tool()
def get_layer_features(ctx: Context, layer_id: str, limit: int = 10) -> str:
    """Retrieve features from a vector layer with an optional limit."""
    qgis = get_qgis_connection()
    result = qgis.send_command("get_layer_features", {"layer_id": layer_id, "limit": limit})
    return json.dumps(result, indent=2)

@mcp.tool()
def execute_processing(ctx: Context, algorithm: str, parameters: dict) -> str:
    """Execute a processing algorithm with the given parameters."""
    qgis = get_qgis_connection()
    result = qgis.send_command("execute_processing", {"algorithm": algorithm, "parameters": parameters})
    return json.dumps(result, indent=2)


@mcp.tool()
def save_project(ctx: Context, path: str = None) -> str:
    """Save the current project to the given path, or to the current project path if not specified."""
    qgis = get_qgis_connection()
    params = {}
    if path:
        params["path"] = path
    result = qgis.send_command("save_project", params)
    return json.dumps(result, indent=2)


@mcp.tool()
def render_map(ctx: Context, path: str, width: int = 800, height: int = 600) -> str:
    """Render the current map view to an image file with the specified dimensions."""
    qgis = get_qgis_connection()
    result = qgis.send_command("render_map", {"path": path, "width": width, "height": height})
    return json.dumps(result, indent=2)


@mcp.tool()
def execute_code(ctx: Context, code: str) -> str:
    """Execute arbitrary PyQGIS code provided as a string."""
    qgis = get_qgis_connection()
    result = qgis.send_command("execute_code", {"code": code})
    return json.dumps(result, indent=2)


@mcp.tool()
def validate_layer(ctx: Context, layer_id: str, check_geometry: bool = True, sample_invalid: int = 20) -> str:
    """Inspect CRS, fields, geometry validity, empty geometries, and raster metadata."""
    qgis = get_qgis_connection()
    result = qgis.send_command("validate_layer", {"layer_id": layer_id, "check_geometry": check_geometry, "sample_invalid": sample_invalid})
    return json.dumps(result, indent=2)


@mcp.tool()
def check_crs_consistency(ctx: Context, layer_ids: list = None) -> str:
    """Check whether selected project layers use a consistent CRS."""
    qgis = get_qgis_connection()
    params = {}
    if layer_ids:
        params["layer_ids"] = layer_ids
    result = qgis.send_command("check_crs_consistency", params)
    return json.dumps(result, indent=2)


@mcp.tool()
def reproject_layer(ctx: Context, layer_id: str, target_crs: str, output_path: str) -> str:
    """Reproject a vector layer to a target CRS and add the result to the project."""
    qgis = get_qgis_connection()
    result = qgis.send_command("reproject_layer", {"layer_id": layer_id, "target_crs": target_crs, "output_path": output_path})
    return json.dumps(result, indent=2)


@mcp.tool()
def clip_vector(ctx: Context, input_layer_id: str, overlay_layer_id: str, output_path: str) -> str:
    """Clip a vector layer by a polygon overlay layer."""
    qgis = get_qgis_connection()
    result = qgis.send_command("clip_vector", {"input_layer_id": input_layer_id, "overlay_layer_id": overlay_layer_id, "output_path": output_path})
    return json.dumps(result, indent=2)


@mcp.tool()
def intersection(ctx: Context, input_layer_id: str, overlay_layer_id: str, output_path: str, input_fields: list = None, overlay_fields: list = None) -> str:
    """Intersect two vector layers and write the result to a file."""
    qgis = get_qgis_connection()
    result = qgis.send_command("intersection", {
        "input_layer_id": input_layer_id,
        "overlay_layer_id": overlay_layer_id,
        "output_path": output_path,
        "input_fields": input_fields or [],
        "overlay_fields": overlay_fields or [],
    })
    return json.dumps(result, indent=2)


@mcp.tool()
def difference(ctx: Context, input_layer_id: str, overlay_layer_id: str, output_path: str) -> str:
    """Erase overlay geometry from an input vector layer."""
    qgis = get_qgis_connection()
    result = qgis.send_command("difference", {"input_layer_id": input_layer_id, "overlay_layer_id": overlay_layer_id, "output_path": output_path})
    return json.dumps(result, indent=2)


@mcp.tool()
def join_attributes_by_location(ctx: Context, input_layer_id: str, join_layer_id: str, output_path: str, predicate: list = None, join_fields: list = None, method: int = 0, discard_nonmatching: bool = False, prefix: str = "join_") -> str:
    """Spatially join attributes from one vector layer to another."""
    qgis = get_qgis_connection()
    result = qgis.send_command("join_attributes_by_location", {
        "input_layer_id": input_layer_id,
        "join_layer_id": join_layer_id,
        "output_path": output_path,
        "predicate": predicate or [0],
        "join_fields": join_fields or [],
        "method": method,
        "discard_nonmatching": discard_nonmatching,
        "prefix": prefix,
    })
    return json.dumps(result, indent=2)


@mcp.tool()
def calculate_area_fields(ctx: Context, layer_id: str, area_field: str = "area_m2", hectare_field: str = "area_ha", precision: int = 2) -> str:
    """Add or update polygon area fields in-place, with source backup when possible."""
    qgis = get_qgis_connection()
    result = qgis.send_command("calculate_area_fields", {"layer_id": layer_id, "area_field": area_field, "hectare_field": hectare_field, "precision": precision})
    return json.dumps(result, indent=2)


@mcp.tool()
def summarize_area_by_zone(ctx: Context, layer_id: str, group_field: str, area_field: str = None) -> str:
    """Summarize polygon area totals and percentages by an attribute field."""
    qgis = get_qgis_connection()
    params = {"layer_id": layer_id, "group_field": group_field}
    if area_field:
        params["area_field"] = area_field
    result = qgis.send_command("summarize_area_by_zone", params)
    return json.dumps(result, indent=2)


@mcp.tool()
def select_by_expression(ctx: Context, layer_id: str, expression: str, method: int = 0) -> str:
    """Select vector features by a QGIS expression."""
    qgis = get_qgis_connection()
    result = qgis.send_command("select_by_expression", {"layer_id": layer_id, "expression": expression, "method": method})
    return json.dumps(result, indent=2)


@mcp.tool()
def export_selected_features(ctx: Context, layer_id: str, output_path: str) -> str:
    """Export currently selected vector features to a file."""
    qgis = get_qgis_connection()
    result = qgis.send_command("export_selected_features", {"layer_id": layer_id, "output_path": output_path})
    return json.dumps(result, indent=2)


@mcp.tool()
def clip_raster_by_mask(ctx: Context, raster_layer_id: str, mask_layer_id: str, output_path: str, crop_to_cutline: bool = True, alpha_band: bool = True) -> str:
    """Clip a raster by a vector mask and add the result to the project."""
    qgis = get_qgis_connection()
    result = qgis.send_command("clip_raster_by_mask", {"raster_layer_id": raster_layer_id, "mask_layer_id": mask_layer_id, "output_path": output_path, "crop_to_cutline": crop_to_cutline, "alpha_band": alpha_band})
    return json.dumps(result, indent=2)


@mcp.tool()
def zonal_statistics(ctx: Context, raster_layer_id: str, zone_layer_id: str, output_path: str, prefix: str = "z_", statistics: list = None) -> str:
    """Calculate raster statistics for polygon zones into a new vector file."""
    qgis = get_qgis_connection()
    result = qgis.send_command("zonal_statistics", {"raster_layer_id": raster_layer_id, "zone_layer_id": zone_layer_id, "output_path": output_path, "prefix": prefix, "statistics": statistics})
    return json.dumps(result, indent=2)


@mcp.tool()
def cad_to_gpkg(ctx: Context, cad_path: str, output_path: str) -> str:
    """Convert a CAD file (DXF/DWG) to GeoPackage and add it to the project."""
    qgis = get_qgis_connection()
    result = qgis.send_command("cad_to_gpkg", {"cad_path": cad_path, "output_path": output_path})
    return json.dumps(result, indent=2)




@mcp.tool()
def slope(ctx: Context, raster_layer_id: str, output_path: str) -> str:
    """Calculate slope (degrees) from a DEM raster."""
    qgis = get_qgis_connection()
    result = qgis.send_command("slope", {"raster_layer_id": raster_layer_id, "output_path": output_path})
    return json.dumps(result, indent=2)


@mcp.tool()
def aspect(ctx: Context, raster_layer_id: str, output_path: str) -> str:
    """Calculate aspect (slope direction) from a DEM raster."""
    qgis = get_qgis_connection()
    result = qgis.send_command("aspect", {"raster_layer_id": raster_layer_id, "output_path": output_path})
    return json.dumps(result, indent=2)


@mcp.tool()
def contour(ctx: Context, raster_layer_id: str, output_path: str, interval: float = 100) -> str:
    """Generate contour lines from a DEM raster."""
    qgis = get_qgis_connection()
    result = qgis.send_command("contour", {"raster_layer_id": raster_layer_id, "output_path": output_path, "interval": interval})
    return json.dumps(result, indent=2)


@mcp.tool()
def create_grid(ctx: Context, output_path: str, extent_layer_id: str, spacing: float = 1000) -> str:
    """Create a rectangular grid (fishnet) over a layer's extent."""
    qgis = get_qgis_connection()
    result = qgis.send_command("create_grid", {"output_path": output_path, "extent_layer_id": extent_layer_id, "spacing": spacing})
    return json.dumps(result, indent=2)


@mcp.tool()
def idw_interpolation(ctx: Context, point_layer_id: str, value_field: str, output_path: str, pixel_size: float = 100) -> str:
    """IDW interpolation from point data to raster."""
    qgis = get_qgis_connection()
    result = qgis.send_command("idw_interpolation", {"point_layer_id": point_layer_id, "value_field": value_field, "output_path": output_path, "pixel_size": pixel_size})
    return json.dumps(result, indent=2)


@mcp.tool()
def cut_fill(ctx: Context, dem_layer_id: str, design_surface_layer_id: str, output_path: str) -> str:
    """Calculate cut/fill by subtracting design surface from DEM. Positive=cut, Negative=fill."""
    qgis = get_qgis_connection()
    result = qgis.send_command("cut_fill", {"dem_layer_id": dem_layer_id, "design_surface_layer_id": design_surface_layer_id, "output_path": output_path})
    return json.dumps(result, indent=2)



# Project structure, controlled editing, and delivery diagnostics.
def _call(command: str, params: dict = None) -> str:
    result = get_qgis_connection().send_command(command, params or {})
    return json.dumps(result, indent=2, ensure_ascii=False, default=str)


@mcp.tool()
def inspect_project_state(ctx: Context) -> str:
    """Inspect the current QGIS project, layer hierarchy, variables, layouts, and unsaved state."""
    return _call("inspect_project_state")


@mcp.tool()
def get_layer_tree(ctx: Context) -> str:
    """Return the real QGIS group/layer tree with visibility and order."""
    return _call("get_layer_tree")


@mcp.tool()
def inspect_layer(ctx: Context, layer_id: str) -> str:
    """Inspect a layer's source, CRS, extent, schema, feature count, and edit/selection state."""
    return _call("inspect_layer", {"layer_id": layer_id})


@mcp.tool()
def get_project_diagnostics(ctx: Context) -> str:
    """Report invalid layers, empty vector layers, active edits, CRS consistency, and save risks."""
    return _call("get_project_diagnostics")


@mcp.tool()
def query_features(ctx: Context, layer_id: str, expression: str = None, fields: list = None, limit: int = 100, selected_only: bool = False) -> str:
    """Read selected or expression-filtered vector attributes without editing data."""
    return _call("query_features", {"layer_id": layer_id, "expression": expression, "fields": fields, "limit": limit, "selected_only": selected_only})


@mcp.tool()
def get_layer_statistics(ctx: Context, layer_id: str, fields: list = None, expression: str = None) -> str:
    """Calculate null, unique, and numeric summary statistics for matching vector features."""
    return _call("get_layer_statistics", {"layer_id": layer_id, "fields": fields, "expression": expression})


@mcp.tool()
def validate_expression(ctx: Context, layer_id: str, expression: str) -> str:
    """Validate a QGIS expression and count matching features without writing."""
    return _call("validate_expression", {"layer_id": layer_id, "expression": expression})


@mcp.tool()
def manage_selection(ctx: Context, layer_id: str, operation: str = "get", expression: str = None, feature_ids: list = None) -> str:
    """Read or update the in-memory QGIS selection; this never writes the data source."""
    return _call("manage_selection", {"layer_id": layer_id, "operation": operation, "expression": expression, "feature_ids": feature_ids})


@mcp.tool()
def calculate_field(ctx: Context, layer_id: str, field_name: str, expression: str, filter_expression: str = None, dry_run: bool = True) -> str:
    """Preview or calculate an existing field in a short guarded transaction. dry_run defaults to true."""
    return _call("calculate_field", {"layer_id": layer_id, "field_name": field_name, "expression": expression, "filter_expression": filter_expression, "dry_run": dry_run})


@mcp.tool()
def update_feature_attributes(ctx: Context, layer_id: str, changes: dict, expression: str = None, feature_ids: list = None, dry_run: bool = True) -> str:
    """Preview or apply named attribute updates only; geometry writes are excluded. dry_run defaults to true."""
    return _call("update_feature_attributes", {"layer_id": layer_id, "changes": changes, "expression": expression, "feature_ids": feature_ids, "dry_run": dry_run})


@mcp.tool()
def delete_features(ctx: Context, layer_id: str, expression: str = None, feature_ids: list = None, dry_run: bool = True) -> str:
    """Preview or delete explicitly matched vector features in a short guarded transaction. dry_run defaults to true."""
    return _call("delete_features", {"layer_id": layer_id, "expression": expression, "feature_ids": feature_ids, "dry_run": dry_run})


@mcp.tool()
def validate_project_for_delivery(ctx: Context) -> str:
    """Check project path, unsaved changes, invalid sources, active edits, and CRS risks before delivery."""
    return _call("validate_project_for_delivery")


@mcp.tool()
def validate_processing_result(ctx: Context, layer_id: str = None, output_path: str = None, expectations: dict = None) -> str:
    """Verify a result layer or output file against type, CRS, and feature-count expectations."""
    return _call("validate_processing_result", {"layer_id": layer_id, "output_path": output_path, "expectations": expectations})


@mcp.tool()
def verify_output_file(ctx: Context, path: str, expected_type: str = None) -> str:
    """Check that an output path exists and QGIS can reopen it as a vector, raster, or project file."""
    return _call("verify_output_file", {"path": path, "expected_type": expected_type})


@mcp.tool()
def get_operation_log(ctx: Context, limit: int = 50) -> str:
    """Return the bounded audit log for commands handled by this QGIS plugin instance."""
    return _call("get_operation_log", {"limit": limit})


@mcp.tool()
def capture_project_state(ctx: Context) -> str:
    """Capture a timestamped read-only project and diagnostics snapshot for before/after comparison."""
    return _call("capture_project_state")


def main():
    """Run the MCP server"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    mcp.run()

if __name__ == "__main__":
    main()
