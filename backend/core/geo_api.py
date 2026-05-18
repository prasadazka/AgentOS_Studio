"""
Geo API — serve geospatial output files for the Map View tab.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

# Regex to extract file paths from GeoExportTool markdown output
GEO_FILE_RE = re.compile(
    r"\*\*File:\*\*\s*(.+\.(?:geojson|gpkg|shp|csv))", re.IGNORECASE
)

# Allowed root directories for serving files
ALLOWED_ROOTS = [
    os.path.expanduser("~"),
]
_env_roots = os.environ.get("GEO_ALLOWED_ROOTS", "")
if _env_roots:
    ALLOWED_ROOTS.extend(_env_roots.split(";"))

ALLOWED_EXTENSIONS = {".geojson", ".json"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def _validate_path(file_path: str) -> tuple[bool, str]:
    """Validate that a file path is safe to serve."""
    resolved = os.path.realpath(file_path)

    # Check allowed roots
    if not any(
        resolved.startswith(os.path.realpath(root)) for root in ALLOWED_ROOTS
    ):
        return False, "Path is outside allowed directories"

    ext = Path(resolved).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Extension '{ext}' not allowed (only .geojson, .json)"

    if not os.path.isfile(resolved):
        return False, "File not found"

    if os.path.getsize(resolved) > MAX_FILE_SIZE:
        return False, "File exceeds 50 MB limit"

    return True, resolved


def list_geo_files() -> list[dict]:
    """Scan completed workflow runs for geo output file paths."""
    from db.database import get_db

    db = get_db()
    rows = db.execute(
        "SELECT id, workflow_id, output, node_states_json FROM workflow_runs "
        "WHERE status = 'completed' ORDER BY finished_at DESC LIMIT 100"
    ).fetchall()

    seen = set()
    files = []

    for row in rows:
        # Search in final output and node states
        texts = [row["output"] or ""]
        try:
            ns = json.loads(row["node_states_json"] or "{}")
            for node_state in ns.values():
                if isinstance(node_state, dict):
                    texts.append(node_state.get("output", ""))
        except (json.JSONDecodeError, Exception):
            pass

        for text in texts:
            for match in GEO_FILE_RE.findall(text):
                fpath = match.strip()
                if fpath in seen:
                    continue
                seen.add(fpath)

                if os.path.isfile(fpath):
                    stat = os.stat(fpath)
                    files.append({
                        "path": fpath,
                        "filename": os.path.basename(fpath),
                        "size_bytes": stat.st_size,
                        "modified_at": datetime.fromtimestamp(
                            stat.st_mtime
                        ).isoformat(),
                        "workflow_id": row["workflow_id"],
                        "run_id": row["id"],
                    })

    return files


def serve_geo_file(file_path: str) -> dict:
    """Read and return a GeoJSON file as a dict."""
    valid, result = _validate_path(file_path)
    if not valid:
        raise ValueError(result)

    resolved = result
    with open(resolved, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Validate it's GeoJSON
    geo_type = data.get("type", "") if isinstance(data, dict) else ""
    valid_types = {
        "FeatureCollection", "Feature", "Point", "MultiPoint",
        "LineString", "MultiLineString", "Polygon", "MultiPolygon",
        "GeometryCollection",
    }
    if geo_type not in valid_types:
        raise ValueError(f"Not valid GeoJSON (type='{geo_type}')")

    return data
