#!/bin/bash
# Replace `<repo-directory>` with the local checkout path before running.
cd "${QGIS_MCP_REPO:-$HOME/projects/qgis-4.0-mcp-public}" && PYTHONPATH=src exec uv run python -m qgis_mcp.qgis_mcp_server
