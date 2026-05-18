"""
Workflow Template Registry
--------------------------
Pre-built workflow templates that users can instantiate from the UI.
Each template defines a complete graph_json (nodes + edges) ready to
open in the visual workflow editor.
"""

from typing import Optional

# =============================================================================
# Multi-File Merge Template
# =============================================================================

MULTI_FILE_MERGE_TEMPLATE = {
    "id": "multi_file_merge",
    "name": "Multi-File Merge",
    "description": (
        "Upload multiple data files (CSV, JSON, Excel, TXT), an AI agent analyzes "
        "schemas, aligns columns if needed, merges data, and exports the result."
    ),
    "category": "data",
    "icon": "merge",
    "tags": ["merge", "union", "csv", "excel", "combine", "data"],
    "node_count": 5,
    "graph_json": {
        "nodes": [
            {
                "id": "start_1",
                "type": "start",
                "position": {"x": 50, "y": 200},
                "data": {
                    "type": "start",
                    "label": "Upload Files",
                    "inputFields": [
                        {
                            "name": "file_1",
                            "label": "First File",
                            "type": "file",
                            "required": True,
                            "placeholder": "CSV, JSON, Excel, TXT, Parquet",
                        },
                        {
                            "name": "file_2",
                            "label": "Second File",
                            "type": "file",
                            "required": True,
                            "placeholder": "CSV, JSON, Excel, TXT, Parquet",
                        },
                        {
                            "name": "file_3",
                            "label": "Third File (optional)",
                            "type": "file",
                            "required": False,
                            "placeholder": "Leave empty if merging only 2 files",
                        },
                        {
                            "name": "merge_mode",
                            "label": "Merge Mode",
                            "type": "select",
                            "required": True,
                            "options": ["outer", "inner"],
                            "defaultValue": "outer",
                        },
                        {
                            "name": "dedup",
                            "label": "Remove Duplicates",
                            "type": "select",
                            "required": True,
                            "options": ["yes", "no"],
                            "defaultValue": "yes",
                        },
                        {
                            "name": "export_format",
                            "label": "Export Format",
                            "type": "select",
                            "required": True,
                            "options": ["csv", "json", "excel", "parquet", "sqlite"],
                            "defaultValue": "csv",
                        },
                        {
                            "name": "output_path",
                            "label": "Output Directory",
                            "type": "text",
                            "required": True,
                            "placeholder": "e.g. C:/Users/DELL/Documents/output",
                        },
                    ],
                },
            },
            {
                "id": "agent_merge",
                "type": "agent",
                "position": {"x": 400, "y": 200},
                "data": {
                    "type": "agent",
                    "label": "Merge Agent",
                    "agentName": "MergeAgent",
                },
            },
            {
                "id": "approval_review",
                "type": "approval",
                "position": {"x": 750, "y": 200},
                "data": {
                    "type": "approval",
                    "label": "Review Result",
                    "approvalPrompt": (
                        "Review the merge agent's output above. "
                        "Approve if the merge completed successfully, or reject to discard."
                    ),
                    "approvalTimeout": 600,
                    "autoApprove": False,
                },
            },
            {
                "id": "agent_summary",
                "type": "agent",
                "position": {"x": 1100, "y": 200},
                "data": {
                    "type": "agent",
                    "label": "Summary Agent",
                    "agentName": "MergeSummaryAgent",
                },
            },
            {
                "id": "end_1",
                "type": "end",
                "position": {"x": 1400, "y": 200},
                "data": {
                    "type": "end",
                    "label": "Done",
                },
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source": "start_1",
                "target": "agent_merge",
                "animated": True,
                "style": {"stroke": "#94a3b8", "strokeWidth": 2},
            },
            {
                "id": "e2",
                "source": "agent_merge",
                "target": "approval_review",
                "animated": True,
                "style": {"stroke": "#94a3b8", "strokeWidth": 2},
            },
            {
                "id": "e3",
                "source": "approval_review",
                "target": "agent_summary",
                "animated": True,
                "style": {"stroke": "#94a3b8", "strokeWidth": 2},
            },
            {
                "id": "e4",
                "source": "agent_summary",
                "target": "end_1",
                "animated": True,
                "style": {"stroke": "#94a3b8", "strokeWidth": 2},
            },
        ],
    },
}


# =============================================================================
# Geo R-Tree Indexing Template
# =============================================================================

GEO_RTREE_TEMPLATE = {
    "id": "geo_rtree_indexing",
    "name": "Geo R-Tree Indexing",
    "description": (
        "Load spatial data (CSV, Excel, JSON with lat/lon), build an R-Tree "
        "spatial index, run bounding-box and radius queries, then export as "
        "GeoJSON, GeoPackage, Shapefile, or CSV with WKT."
    ),
    "category": "geospatial",
    "icon": "globe",
    "tags": ["geospatial", "r-tree", "spatial", "gis", "coordinates", "export"],
    "node_count": 6,
    "graph_json": {
        "nodes": [
            {
                "id": "start_1",
                "type": "start",
                "position": {"x": 50, "y": 200},
                "data": {
                    "type": "start",
                    "label": "Upload Spatial Data",
                    "inputFields": [
                        {
                            "name": "file",
                            "label": "Data File",
                            "type": "file",
                            "required": True,
                            "placeholder": "CSV, JSON, Excel, TXT, Parquet with lat/lon",
                        },
                        {
                            "name": "lat_column",
                            "label": "Latitude Column",
                            "type": "text",
                            "required": False,
                            "placeholder": "Auto-detected if left blank",
                        },
                        {
                            "name": "lon_column",
                            "label": "Longitude Column",
                            "type": "text",
                            "required": False,
                            "placeholder": "Auto-detected if left blank",
                        },
                        {
                            "name": "export_format",
                            "label": "Export Format",
                            "type": "select",
                            "required": True,
                            "options": ["geojson", "geopackage", "csv_with_wkt", "shapefile"],
                            "defaultValue": "geojson",
                        },
                        {
                            "name": "output_path",
                            "label": "Output Directory",
                            "type": "text",
                            "required": True,
                            "placeholder": "e.g. C:/Users/DELL/Documents/output",
                        },
                    ],
                },
            },
            {
                "id": "agent_geo_loader",
                "type": "agent",
                "position": {"x": 400, "y": 200},
                "data": {
                    "type": "agent",
                    "label": "Geo Loader",
                    "agentName": "GeoLoaderAgent",
                },
            },
            {
                "id": "agent_geo_index",
                "type": "agent",
                "position": {"x": 750, "y": 200},
                "data": {
                    "type": "agent",
                    "label": "Geo Indexer",
                    "agentName": "GeoIndexAgent",
                },
            },
            {
                "id": "approval_review",
                "type": "approval",
                "position": {"x": 1100, "y": 200},
                "data": {
                    "type": "approval",
                    "label": "Review Index",
                    "approvalPrompt": (
                        "Review the spatial index results above. "
                        "Approve to proceed with export, or reject to discard."
                    ),
                    "approvalTimeout": 600,
                    "autoApprove": False,
                },
            },
            {
                "id": "agent_geo_export",
                "type": "agent",
                "position": {"x": 1400, "y": 200},
                "data": {
                    "type": "agent",
                    "label": "Geo Export",
                    "agentName": "GeoExportAgent",
                },
            },
            {
                "id": "end_1",
                "type": "end",
                "position": {"x": 1700, "y": 200},
                "data": {
                    "type": "end",
                    "label": "Done",
                },
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source": "start_1",
                "target": "agent_geo_loader",
                "animated": True,
                "style": {"stroke": "#94a3b8", "strokeWidth": 2},
            },
            {
                "id": "e2",
                "source": "agent_geo_loader",
                "target": "agent_geo_index",
                "animated": True,
                "style": {"stroke": "#94a3b8", "strokeWidth": 2},
            },
            {
                "id": "e3",
                "source": "agent_geo_index",
                "target": "approval_review",
                "animated": True,
                "style": {"stroke": "#94a3b8", "strokeWidth": 2},
            },
            {
                "id": "e4",
                "source": "approval_review",
                "target": "agent_geo_export",
                "animated": True,
                "style": {"stroke": "#94a3b8", "strokeWidth": 2},
            },
            {
                "id": "e5",
                "source": "agent_geo_export",
                "target": "end_1",
                "animated": True,
                "style": {"stroke": "#94a3b8", "strokeWidth": 2},
            },
        ],
    },
}


# =============================================================================
# Template Registry
# =============================================================================

_TEMPLATES = [MULTI_FILE_MERGE_TEMPLATE, GEO_RTREE_TEMPLATE]
_TEMPLATE_MAP = {t["id"]: t for t in _TEMPLATES}


def list_templates() -> list:
    """Return all available workflow templates (metadata only, no graph_json)."""
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "description": t["description"],
            "category": t["category"],
            "icon": t["icon"],
            "tags": t["tags"],
            "node_count": t["node_count"],
        }
        for t in _TEMPLATES
    ]


def get_template(template_id: str) -> Optional[dict]:
    """Get a full template by ID (includes graph_json)."""
    return _TEMPLATE_MAP.get(template_id)
