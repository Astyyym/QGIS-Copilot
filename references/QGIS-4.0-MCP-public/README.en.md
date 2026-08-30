<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/Lang-中文-red?style=for-the-badge" alt="中文"></a>
  <a href="README.en.md"><img src="https://img.shields.io/badge/Lang-English-blue?style=for-the-badge" alt="English"></a>
</p>

# QGIS 4 MCP Plugin

<p align="center">
  <img src="https://img.shields.io/badge/QGIS-4.x-589632?style=flat-square&logo=qgis" alt="QGIS 4.x">
  <img src="https://img.shields.io/badge/Python-≥3.12-3776AB?style=flat-square&logo=python" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/license-GPL--2.0-blue?style=flat-square" alt="License GPL-2.0">
  <img src="https://img.shields.io/badge/MCP-1.3.0+-purple?style=flat-square" alt="MCP 1.3.0+">
</p>

**QGIS 4 MCP Plugin** bridges AI assistants (Claude, Cursor, Codex, etc.) with QGIS 4.x via the [Model Context Protocol (MCP)](https://github.com/modelcontextprotocol). It exposes PyQGIS capabilities as MCP tools, enabling natural-language-driven GIS workflows.

This is a **QGIS 4.x compatible fork** of [jjsantos01/qgis_mcp](https://github.com/jjsantos01/qgis_mcp) (⭐984), which only supports QGIS 3.x. The original was inspired by [BlenderMCP](https://github.com/ahujasid/blender-mcp) by Siddharth Ahuja.

---

## Architecture

```
┌─────────────────────┐     stdio (MCP)      ┌─────────────────────┐
│   AI Client         │ ◄─────────────────► │   MCP Server         │
│   (Claude/Cursor/   │     JSON-RPC 2.0     │   (Python / FastMCP) │
│    Codex/any MCP)   │                      │   src/qgis_mcp/      │
└─────────────────────┘                      └─────────┬───────────┘
                                                        │ TCP Socket
                                                        │ port 9877
                                                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                     QGIS (4.x)                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Astyyym QGIS MCP Plugin (astyyym_qgis_mcp/)                       │  │
│  │  ┌─────────────────┐    ┌──────────────────────────────┐  │  │
│  │  │ Dock Widget     │    │  Command Dispatcher           │  │  │
│  │  │ (Start/Stop)    │───►│ → 51 tool handlers             │  │  │
│  │  └─────────────────┘    │  → JSON-RPC over TCP          │  │  │
│  │                         └──────────────┬───────────────┘  │  │
│  │                                        ▼                  │  │
│  │                         ┌──────────────────────────────┐  │  │
│  │                         │  PyQGIS API                   │  │  │
│  │                         │  (QgsProject, QgsVectorLayer, │  │  │
│  │                         │   processing, map canvas...)  │  │  │
│  │                         └──────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### How it works

1. **QGIS plugin** opens a TCP socket server (default port **9877**) inside QGIS and listens for JSON-RPC commands.
2. **MCP Server** (standalone Python process) connects to QGIS over TCP and exposes each command as an MCP tool via `FastMCP`.
3. **AI Client** (Claude Desktop, Cursor, etc.) communicates with the MCP Server over stdio using the standard MCP protocol, discovering and invoking tools automatically.

---

## Key Differences from Upstream

| Change | Description |
|--------|-------------|
| **QGIS version detection** | `_qgis_major_version()` helper detects QGIS version at runtime (3 or 4) |
| **Layer type detection** | Uses `Qgis.LayerType.Vector`/`Raster` on QGIS 4, `QgsMapLayer.VectorLayer`/`RasterLayer` on QGIS 3 |
| **Geometry type helpers** | `_geometry_type_str()` / `_geometry_type_str_from_layer()` handle the QGIS 4 enum change |
| **Message level helper** | `_msg_level()` resolves `Qgis.MessageLevel` vs `Qgis` attribute differences |
| **Plugin metadata** | `qgisMaximumVersion=4.99` in `metadata.txt` |
| **Python version** | `requires-python = ">=3.12"` to match QGIS 4 |
| **Canvas API** | `zoom_to_layer` uses `canvas.setExtent()` + `canvas.refresh()` (`zoomToActiveLayer` removed in QGIS 4) |
| **Processing context** | Added `QgsProcessingContext` and `QgsProcessingFeedback` |
| **Attribute serialization** | Safe JSON serialization for QVariant/NULL values |
| **Layer tree safety** | Null-safe tree lookup and group path info |

All changes verified against [QGIS 4.0 official PyQGIS docs](https://qgis.org/pyqgis/4.0/), with runtime validation on QGIS 4.0.0-Norrköping.

---

## Requirements

- **[QGIS 4.x](https://qgis.org/)**
- **Python ≥ 3.12**
- **[uv](https://docs.astral.sh/uv/)**
- **Claude Desktop** or any MCP-compatible client (Cursor, Continue.dev, etc.)

---

## Installation

### 1. Install the QGIS Plugin

Copy `astyyym_qgis_mcp/` to your QGIS plugins folder:

```bash
# Linux
cp -r astyyym_qgis_mcp ~/.local/share/QGIS/QGIS4/profiles/default/python/plugins/

# Windows via WSL — replace `<WindowsUser>` with your Windows account name
cp -r astyyym_qgis_mcp /mnt/c/Users/<WindowsUser>/AppData/Roaming/QGIS/QGIS4/profiles/default/python/plugins/

# macOS
cp -r astyyym_qgis_mcp ~/Library/Application\ Support/QGIS/QGIS4/profiles/default/python/plugins/
```

In QGIS: **Plugins → Manage and Install Plugins** → enable **Astyyym QGIS MCP**.

### 2. Set Up the MCP Server

```bash
cd /path/to/qgis-4-0-mcp-public
uv sync
uv run python -c "from qgis_mcp.qgis_mcp_server import mcp; print('MCP server loaded')"
```

### 3. Configure Claude Desktop

Add to your `claude_desktop_config.json`:

**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Linux:** `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "qgis-mcp": {
      "command": "uv",
      "args": [
        "--project",
        "/path/to/qgis-4.0-mcp-public",
        "run",
        "python",
        "-m",
        "qgis_mcp.qgis_mcp_server"
      ]
    }
  }
}
```

### 4. Other Clients

**Cursor:** Settings → Features → MCP Servers → command: `uv --project /path/to/qgis-4.0-mcp-public run python -m qgis_mcp.qgis_mcp_server`

**Continue.dev:** Add to `~/.continue/config.json`.

---

## Usage

### Quick Start

1. **Launch QGIS** → enable plugin → open dock widget → **Start Server**
2. Open **Claude Desktop** — tools auto-discover
3. Start prompting in natural language

### Example Prompts

> **"Load the project at /data/my_map.qgz and tell me what layers are in it."**

> **"Add the shapefile at /data/roads.shp as a vector layer and zoom to it."**

> **"Run a buffer analysis on the 'schools' layer with a 500-meter radius."**

> **"Get the first 5 features from the 'parcels' layer and show their attributes."**

> **"Save the current project to /tmp/analysis.qgz and render the map to /tmp/map.png."**

---

## Available Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `ping` | Connection test | None |
| `get_qgis_info` | QGIS version info | None |
| `load_project` | Load QGS/QGZ project | `path` |
| `create_new_project` | Create new project | `path` |
| `get_project_info` | Project information | None |
| `add_vector_layer` | Add vector layer | `path`, `name?`, `provider?` |
| `add_raster_layer` | Add raster layer | `path`, `name?`, `provider?` |
| `get_layers` | List all layers | None |
| `remove_layer` | Remove layer by ID | `layer_id` |
| `zoom_to_layer` | Zoom to layer extent | `layer_id` |
| `get_layer_features` | Query layer features | `layer_id`, `limit?` |
| `execute_processing` | Run Processing algorithm | `algorithm`, `parameters` |
| `execute_code` | Run arbitrary PyQGIS code | `code` |
| `save_project` | Save project | `path?` |
| `render_map` | Render map canvas to image | `path`, `width?`, `height?` |
| **Custom Extensions** | | |
| `reorder_layers` | Reorder layers safely (first = top) | `layer_ids: [ordered list]` |
| `rename_layer` | Rename a layer | `layer_id`, `name` |
| `export_layer` | Export layer to file | `layer_id`, `output_path` |
| `zoom_to_feature` | Zoom to feature by expression | `layer_id`, `expression` |
| `create_buffer` | Buffer with auto CRS reprojection | `layer_id`, `distance(m)`, `output_path`, `dissolve?` |
| `add_field` | Add field with expression/ranking | `layer_id`, `field_name`, `field_type`, `expression?`, `rank_by?` |
| `delete_fields` | Delete multiple fields | `layer_id`, `field_names: [list]` |
| `get_fields` | Get field names and types | `layer_id` |
| `reorder_fields` | Safe field reorder (new file, no in-place mod) | `layer_id`, `field_order: [ordered names]`, `output_path?` |
| `validate_layer` | Layer QA: CRS, fields, empty/invalid geometries, raster metadata | `layer_id`, `check_geometry?`, `sample_invalid?` |
| `check_crs_consistency` | Check CRS consistency across project or selected layers | `layer_ids?` |
| `reproject_layer` | Reproject vector layer and auto-add result | `layer_id`, `target_crs`, `output_path` |
| `clip_vector` | Clip vector layer by overlay polygon | `input_layer_id`, `overlay_layer_id`, `output_path` |
| `intersection` | Vector overlay intersection | `input_layer_id`, `overlay_layer_id`, `output_path`, `input_fields?`, `overlay_fields?` |
| `difference` | Vector erase/difference | `input_layer_id`, `overlay_layer_id`, `output_path` |
| `join_attributes_by_location` | Spatial attribute join | `input_layer_id`, `join_layer_id`, `output_path`, `predicate?`, `join_fields?` |
| `calculate_area_fields` | Calculate area fields in m²/ha with backup when possible | `layer_id`, `area_field?`, `hectare_field?`, `precision?` |
| `summarize_area_by_zone` | Summarize area totals and percentages by field | `layer_id`, `group_field`, `area_field?` |
| `select_by_expression` | Select features using a QGIS expression | `layer_id`, `expression`, `method?` |
| `export_selected_features` | Export current selected features | `layer_id`, `output_path` |
| `clip_raster_by_mask` | Clip raster by vector mask | `raster_layer_id`, `mask_layer_id`, `output_path`, `crop_to_cutline?`, `alpha_band?` |
| `zonal_statistics` | Calculate raster zonal statistics into vector zones | `raster_layer_id`, `zone_layer_id`, `output_path`, `prefix?`, `statistics?` |

---

### Project Structure, Controlled Editing, and Delivery Diagnostics

| Tool | Description | Parameters |
|------|-------------|------------|
| `inspect_project_state` | Inspect project, layer tree, variables, layouts, and unsaved state | None |
| `get_layer_tree` | Return the real group/layer hierarchy, order, and visibility | None |
| `inspect_layer` | Inspect source, CRS, extent, schema, selection, and edit state | `layer_id` |
| `get_project_diagnostics` | Summarize invalid/empty layers, active edits, and CRS risks | None |
| `query_features` | Read expression-filtered or selected attributes without source writes | `layer_id`, `expression?`, `fields?`, `limit?`, `selected_only?` |
| `get_layer_statistics` | Calculate null, unique, and numeric field statistics | `layer_id`, `fields?`, `expression?` |
| `validate_expression` | Validate a QGIS expression and count its matches | `layer_id`, `expression` |
| `manage_selection` | Read or update QGIS' in-memory selection without source writes | `layer_id`, `operation?`, `expression?`, `feature_ids?` |
| `calculate_field` | Preview or calculate an existing field; dry-run by default | `layer_id`, `field_name`, `expression`, `filter_expression?`, `dry_run?` |
| `update_feature_attributes` | Preview or batch-update attributes only; no geometry writes; dry-run by default | `layer_id`, `changes`, `expression?`, `feature_ids?`, `dry_run?` |
| `delete_features` | Preview or delete explicitly matched features; dry-run by default | `layer_id`, `expression?`, `feature_ids?`, `dry_run?` |
| `validate_project_for_delivery` | Check project path, unsaved changes, invalid sources, edits, and CRS | None |
| `validate_processing_result` | Verify result-layer or output-file type, CRS, and feature-count expectations | `layer_id?`, `output_path?`, `expectations?` |
| `verify_output_file` | Check that output exists and QGIS can reopen it | `path`, `expected_type?` |
| `get_operation_log` | Return the audit log from this plugin instance | `limit?` |
| `capture_project_state` | Capture a timestamped project and diagnostics snapshot | None |

> Write tools default to `dry_run=true` and only report the affected feature count. Set `dry_run=false` explicitly to commit. Attribute updates and deletion also require an `expression` or `feature_ids` to prevent unfiltered bulk writes.

## Security

> **This plugin allows arbitrary PyQGIS code execution via TCP socket.** The server binds `0.0.0.0:9877` (default port). Any host that can reach this port on your network can send commands.

- **Do NOT expose to the public internet.** Port 9877 has no authentication or encryption.
- **Recommended use:** AI agent (Hermes/Claude) connecting from localhost or WSL via `172.x.x.x` internal IP only — don't open across machines.
- **`execute_code` is a double-edged sword:** It can do anything — read/write files, delete layers, commit edits. Use only in trusted environments.
- **Port can be changed** in the plugin UI (default 9877). Check your WSL IP with `ipconfig`.

## Credits

- **Upstream:** [jjsantos01/qgis_mcp](https://github.com/jjsantos01/qgis_mcp) (⭐984)
- **Inspired by:** [BlenderMCP](https://github.com/ahujasid/blender-mcp) by Siddharth Ahuja
- **Protocol:** [Model Context Protocol](https://modelcontextprotocol.io) by Anthropic
- **QGIS 4 compatibility reference:** [evenzur/qgis_3and4_MCP_Plugin](https://github.com/evenzur/qgis_3and4_MCP_Plugin)

## License

[GPL-2.0](LICENSE)
