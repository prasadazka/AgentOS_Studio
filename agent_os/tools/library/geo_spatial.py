"""Geospatial tools — load point data, build R-Tree index, spatial queries, export.

Completely separate from gwdb_* tools. Uses its own _geo_store for GeoDataFrames.
Requires: geopandas, shapely, rtree, pyproj  →  pip install agent-os[geo]
"""

import os
import threading
from typing import Dict, Optional

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Shared GeoDataFrame store (session-scoped, separate from gwdb)
# ---------------------------------------------------------------------------

_geo_store: Dict[str, object] = {}  # name → GeoDataFrame
_geo_lock = threading.Lock()


def _import_geopandas():
    try:
        import geopandas as gpd
        return gpd
    except ImportError as e:
        import sys
        raise ImportError(
            f"geopandas import failed: {e} "
            f"(python={sys.executable}). "
            "Install with: pip install agent-os[geo]"
        ) from e


def _import_shapely():
    try:
        from shapely.geometry import Point, box
        return Point, box
    except ImportError:
        raise ImportError(
            "shapely is required for geospatial tools. "
            "Install with: pip install agent-os[geo]"
        )


def store_geodataframe(name: str, gdf) -> None:
    with _geo_lock:
        _geo_store[name] = gdf


def get_geodataframe(name: str):
    with _geo_lock:
        return _geo_store.get(name)


def list_geodataframes() -> Dict[str, dict]:
    with _geo_lock:
        result = {}
        for name, gdf in _geo_store.items():
            result[name] = {
                "rows": len(gdf),
                "columns": len(gdf.columns),
                "has_sindex": hasattr(gdf, "sindex") and gdf.sindex is not None,
                "crs": str(gdf.crs) if gdf.crs else "None",
            }
        return result


# ---------------------------------------------------------------------------
# Helper: auto-detect lat/lon columns
# ---------------------------------------------------------------------------

_LAT_PATTERNS = ["lat", "latitude", "coordddlat", "coord_lat", "y", "lat_dd"]
_LON_PATTERNS = ["lon", "lng", "longitude", "coordddlong", "coord_lon", "coord_lng", "x", "lon_dd", "long"]


def _detect_coord_columns(columns: list) -> tuple:
    """Auto-detect lat/lon column names from a list of column names."""
    lower_map = {c.lower().strip(): c for c in columns}
    lat_col = None
    lon_col = None

    for pattern in _LAT_PATTERNS:
        for col_lower, col_orig in lower_map.items():
            if pattern == col_lower or col_lower.endswith(pattern):
                lat_col = col_orig
                break
        if lat_col:
            break

    for pattern in _LON_PATTERNS:
        for col_lower, col_orig in lower_map.items():
            if pattern == col_lower or col_lower.endswith(pattern):
                lon_col = col_orig
                break
        if lon_col:
            break

    return lat_col, lon_col


# ---------------------------------------------------------------------------
# Helper: load file as pandas DataFrame
# ---------------------------------------------------------------------------

def _load_file_as_df(file_path: str):
    """Load a file into a pandas DataFrame (auto-detect format)."""
    import pandas as pd

    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".csv":
        return pd.read_csv(file_path)
    elif ext == ".json":
        return pd.read_json(file_path)
    elif ext in (".xlsx", ".xls"):
        return pd.read_excel(file_path)
    elif ext in (".parquet", ".pq"):
        return pd.read_parquet(file_path)
    elif ext in (".txt", ".tsv"):
        # Auto-detect delimiter
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            first_line = f.readline()
        if "|" in first_line:
            return pd.read_csv(file_path, delimiter="|")
        elif "\t" in first_line:
            return pd.read_csv(file_path, delimiter="\t")
        else:
            return pd.read_csv(file_path)
    else:
        return pd.read_csv(file_path)


# ===========================================================================
# Tool 1: geo_load_points
# ===========================================================================

class GeoLoadPointsTool(BaseTool):
    """Load a data file with lat/lon columns, create Point geometries, store as GeoDataFrame."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="geo_load_points",
            description=(
                "Load a data file (CSV, JSON, TXT, Excel, Parquet) containing latitude and "
                "longitude columns. Auto-detects coordinate columns if not specified. Creates "
                "Point geometries and stores as a spatial GeoDataFrame for indexing and queries."
            ),
            category="geo",
            tags=["geo", "spatial", "load", "points", "coordinates", "geodataframe"],
        ))

    def _execute(
        self,
        file_path: str,
        lat_column: str = "",
        lon_column: str = "",
        table_name: str = "",
    ) -> str:
        gpd = _import_geopandas()
        Point, _ = _import_shapely()

        # Validate file exists
        if not os.path.isfile(file_path):
            return f"Error: File not found: {file_path}"

        # Load as DataFrame
        try:
            df = _load_file_as_df(file_path)
        except Exception as e:
            return f"Error loading file: {e}"

        if df.empty:
            return "Error: File loaded but contains no rows."

        # Detect or validate lat/lon columns
        lat_col = lat_column.strip() if lat_column.strip() else None
        lon_col = lon_column.strip() if lon_column.strip() else None

        if not lat_col or not lon_col:
            detected_lat, detected_lon = _detect_coord_columns(list(df.columns))
            lat_col = lat_col or detected_lat
            lon_col = lon_col or detected_lon

        if not lat_col or not lon_col:
            available = ", ".join(df.columns.tolist())
            return (
                f"Error: Could not detect coordinate columns.\n"
                f"Available columns: {available}\n"
                f"Please specify lat_column and lon_column explicitly."
            )

        if lat_col not in df.columns:
            return f"Error: Column '{lat_col}' not found. Available: {', '.join(df.columns)}"
        if lon_col not in df.columns:
            return f"Error: Column '{lon_col}' not found. Available: {', '.join(df.columns)}"

        # Convert to numeric and validate
        import pandas as pd
        df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
        df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")

        null_coords = df[lat_col].isna() | df[lon_col].isna()
        invalid_lat = (df[lat_col] < -90) | (df[lat_col] > 90)
        invalid_lon = (df[lon_col] < -180) | (df[lon_col] > 180)
        invalid_range = (~null_coords) & (invalid_lat | invalid_lon)

        total_rows = len(df)
        null_count = int(null_coords.sum())
        invalid_count = int(invalid_range.sum())
        valid_mask = ~null_coords & ~invalid_range
        valid_count = int(valid_mask.sum())

        # Create GeoDataFrame from valid rows
        valid_df = df[valid_mask].copy()
        geometry = [Point(lon, lat) for lon, lat in zip(valid_df[lon_col], valid_df[lat_col])]
        gdf = gpd.GeoDataFrame(valid_df, geometry=geometry, crs="EPSG:4326")

        # Generate table name
        name = table_name.strip() if table_name.strip() else os.path.splitext(os.path.basename(file_path))[0]
        store_geodataframe(name, gdf)

        # Summary
        bounds = gdf.total_bounds  # [minx, miny, maxx, maxy] = [min_lon, min_lat, max_lon, max_lat]
        output = f"## Loaded: {name}\n\n"
        output += f"- **File:** {os.path.basename(file_path)}\n"
        output += f"- **Total rows:** {total_rows:,}\n"
        output += f"- **Valid points:** {valid_count:,}\n"
        if null_count > 0:
            output += f"- **Null coordinates:** {null_count:,}\n"
        if invalid_count > 0:
            output += f"- **Out-of-range coordinates:** {invalid_count:,}\n"
        output += f"- **Lat column:** {lat_col}\n"
        output += f"- **Lon column:** {lon_col}\n"
        output += f"- **CRS:** EPSG:4326 (WGS 84)\n"
        output += f"- **Bounding box:**\n"
        output += f"  - Lat: {bounds[1]:.6f} to {bounds[3]:.6f}\n"
        output += f"  - Lon: {bounds[0]:.6f} to {bounds[2]:.6f}\n"
        output += f"- **Columns:** {len(gdf.columns)} ({', '.join(c for c in gdf.columns if c != 'geometry')})\n"

        logger.info(f"Loaded {valid_count} points as '{name}'", extra={"file": file_path})
        return output


# ===========================================================================
# Tool 2: geo_build_rtree
# ===========================================================================

class GeoBuildRTreeTool(BaseTool):
    """Build an R-Tree spatial index on a loaded GeoDataFrame."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="geo_build_rtree",
            description=(
                "Build an R-Tree spatial index on a loaded geospatial table. "
                "This dramatically speeds up spatial queries like bounding box search "
                "and radius search. Must be called after loading points with geo_load_points."
            ),
            category="geo",
            tags=["geo", "spatial", "rtree", "index", "performance"],
        ))

    def _execute(self, table_name: str) -> str:
        gpd = _import_geopandas()

        gdf = get_geodataframe(table_name)
        if gdf is None:
            available = ", ".join(list_geodataframes().keys()) or "none"
            return f"Error: Table '{table_name}' not found. Available: {available}"

        # Build spatial index (geopandas does this via .sindex property)
        sindex = gdf.sindex
        bounds = gdf.total_bounds

        output = f"## R-Tree Index Built: {table_name}\n\n"
        output += f"- **Indexed points:** {len(gdf):,}\n"
        output += f"- **Index type:** R-Tree (via rtree/pygeos)\n"
        output += f"- **Bounding box:**\n"
        output += f"  - Lat: {bounds[1]:.6f} to {bounds[3]:.6f}\n"
        output += f"  - Lon: {bounds[0]:.6f} to {bounds[2]:.6f}\n"
        output += f"- **Index size:** {sindex.size} entries\n"
        output += f"- **Status:** Ready for spatial queries\n"

        logger.info(f"Built R-Tree index on '{table_name}' ({len(gdf)} points)")
        return output


# ===========================================================================
# Tool 3: geo_bbox_query
# ===========================================================================

class GeoBBoxQueryTool(BaseTool):
    """Query points within a bounding box using R-Tree spatial index."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="geo_bbox_query",
            description=(
                "Find all points inside a rectangular bounding box using the R-Tree index. "
                "Specify min/max latitude and longitude. Returns matching points and saves "
                "them as a new table for further analysis or export."
            ),
            category="geo",
            tags=["geo", "spatial", "bbox", "query", "search", "window"],
        ))

    def _execute(
        self,
        table_name: str,
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
        result_name: str = "",
    ) -> str:
        gpd = _import_geopandas()
        _, box = _import_shapely()

        gdf = get_geodataframe(table_name)
        if gdf is None:
            available = ", ".join(list_geodataframes().keys()) or "none"
            return f"Error: Table '{table_name}' not found. Available: {available}"

        # Validate bounds
        if min_lat >= max_lat:
            return f"Error: min_lat ({min_lat}) must be less than max_lat ({max_lat})"
        if min_lon >= max_lon:
            return f"Error: min_lon ({min_lon}) must be less than max_lon ({max_lon})"

        # Create bounding box and query
        bbox = box(min_lon, min_lat, max_lon, max_lat)
        candidates = gdf.sindex.query(bbox, predicate="intersects")
        result = gdf.iloc[candidates].copy()

        # Store result
        rname = result_name.strip() if result_name.strip() else f"{table_name}_bbox_result"
        store_geodataframe(rname, result)

        output = f"## Bounding Box Query: {table_name}\n\n"
        output += f"- **Query window:**\n"
        output += f"  - Lat: {min_lat} to {max_lat}\n"
        output += f"  - Lon: {min_lon} to {max_lon}\n"
        output += f"- **Points found:** {len(result):,} (out of {len(gdf):,})\n"
        output += f"- **Saved as:** {rname}\n\n"

        if len(result) > 0:
            sample = result.head(5).drop(columns=["geometry"], errors="ignore")
            output += "### Sample (first 5 rows)\n\n"
            output += sample.to_markdown(index=False) + "\n"

        logger.info(f"BBox query on '{table_name}': {len(result)} hits")
        return output


# ===========================================================================
# Tool 4: geo_radius_query
# ===========================================================================

class GeoRadiusQueryTool(BaseTool):
    """Find points within a radius (km) from a center point."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="geo_radius_query",
            description=(
                "Find all points within a specified radius (in kilometers) from a center "
                "coordinate. Uses the R-Tree index for fast candidate filtering, then "
                "calculates actual geodesic distance for accuracy."
            ),
            category="geo",
            tags=["geo", "spatial", "radius", "nearby", "distance", "search"],
        ))

    def _execute(
        self,
        table_name: str,
        center_lat: float,
        center_lon: float,
        radius_km: float,
        result_name: str = "",
    ) -> str:
        gpd = _import_geopandas()
        Point, box = _import_shapely()

        gdf = get_geodataframe(table_name)
        if gdf is None:
            available = ", ".join(list_geodataframes().keys()) or "none"
            return f"Error: Table '{table_name}' not found. Available: {available}"

        if radius_km <= 0:
            return "Error: radius_km must be positive."

        # Approximate bounding box from radius (1 degree ≈ 111 km)
        deg_offset = radius_km / 111.0
        min_lat = center_lat - deg_offset
        max_lat = center_lat + deg_offset
        min_lon = center_lon - deg_offset
        max_lon = center_lon + deg_offset

        # Fast R-Tree filter with bounding box
        bbox = box(min_lon, min_lat, max_lon, max_lat)
        candidates_idx = gdf.sindex.query(bbox, predicate="intersects")
        candidates = gdf.iloc[candidates_idx].copy()

        if len(candidates) == 0:
            rname = result_name.strip() if result_name.strip() else f"{table_name}_radius_result"
            store_geodataframe(rname, candidates)
            return f"No points found within {radius_km} km of ({center_lat}, {center_lon})."

        # Precise geodesic distance filter
        center = gpd.GeoDataFrame(
            geometry=[Point(center_lon, center_lat)], crs="EPSG:4326"
        )
        # Project to metric CRS for accurate distance
        try:
            metric_crs = candidates.estimate_utm_crs()
            candidates_m = candidates.to_crs(metric_crs)
            center_m = center.to_crs(metric_crs)
        except Exception:
            # Fallback: approximate with degree-based distance
            from shapely.ops import transform
            candidates_m = candidates.copy()
            center_m = center.copy()
            metric_crs = "EPSG:4326"

        distances = candidates_m.geometry.distance(center_m.geometry.iloc[0])
        radius_m = radius_km * 1000
        within = distances <= radius_m

        result = candidates[within.values].copy()
        result["distance_km"] = (distances[within.values].values / 1000).round(2)
        result = result.sort_values("distance_km")

        # Store
        rname = result_name.strip() if result_name.strip() else f"{table_name}_radius_result"
        store_geodataframe(rname, result)

        output = f"## Radius Query: {table_name}\n\n"
        output += f"- **Center:** ({center_lat}, {center_lon})\n"
        output += f"- **Radius:** {radius_km} km\n"
        output += f"- **Points found:** {len(result):,} (out of {len(gdf):,})\n"
        output += f"- **Saved as:** {rname}\n\n"

        if len(result) > 0:
            sample = result.head(10).drop(columns=["geometry"], errors="ignore")
            output += "### Nearest 10 points\n\n"
            output += sample.to_markdown(index=False) + "\n"

        logger.info(f"Radius query on '{table_name}': {len(result)} hits within {radius_km}km")
        return output


# ===========================================================================
# Tool 5: geo_spatial_stats
# ===========================================================================

class GeoSpatialStatsTool(BaseTool):
    """Get spatial statistics and profile of a loaded GeoDataFrame."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="geo_spatial_stats",
            description=(
                "Show spatial statistics for a loaded geospatial table: point count, "
                "bounding box, CRS, coordinate distribution, spatial index status, "
                "and data column summary."
            ),
            category="geo",
            tags=["geo", "spatial", "stats", "profile", "summary"],
        ))

    def _execute(self, table_name: str) -> str:
        gdf = get_geodataframe(table_name)
        if gdf is None:
            available = ", ".join(list_geodataframes().keys()) or "none"
            if not available or available == "none":
                return f"Error: No geospatial tables loaded. Use geo_load_points first."
            return f"Error: Table '{table_name}' not found. Available: {available}"

        bounds = gdf.total_bounds
        has_idx = hasattr(gdf, "sindex") and gdf.sindex is not None and gdf.sindex.size > 0
        data_cols = [c for c in gdf.columns if c != "geometry"]

        # Coordinate stats
        lats = gdf.geometry.y
        lons = gdf.geometry.x

        output = f"## Spatial Profile: {table_name}\n\n"
        output += f"- **Points:** {len(gdf):,}\n"
        output += f"- **CRS:** {gdf.crs}\n"
        output += f"- **Spatial index:** {'Built (R-Tree)' if has_idx else 'Not built'}\n"
        output += f"- **Data columns:** {len(data_cols)}\n\n"

        output += "### Bounding Box\n\n"
        output += f"| | Min | Max |\n"
        output += f"|---|---|---|\n"
        output += f"| Latitude | {bounds[1]:.6f} | {bounds[3]:.6f} |\n"
        output += f"| Longitude | {bounds[0]:.6f} | {bounds[2]:.6f} |\n\n"

        output += "### Coordinate Distribution\n\n"
        output += f"| Stat | Latitude | Longitude |\n"
        output += f"|---|---|---|\n"
        output += f"| Mean | {lats.mean():.6f} | {lons.mean():.6f} |\n"
        output += f"| Std Dev | {lats.std():.6f} | {lons.std():.6f} |\n"
        output += f"| Min | {lats.min():.6f} | {lons.min():.6f} |\n"
        output += f"| Max | {lats.max():.6f} | {lons.max():.6f} |\n\n"

        output += "### Columns\n\n"
        output += "| Column | Type | Non-Null |\n"
        output += "|---|---|---|\n"
        for col in data_cols:
            dtype = str(gdf[col].dtype)
            non_null = int(gdf[col].notna().sum())
            output += f"| {col} | {dtype} | {non_null:,} |\n"

        # List all loaded geo tables
        all_tables = list_geodataframes()
        if len(all_tables) > 1:
            output += f"\n### All Loaded Geo Tables\n\n"
            output += "| Table | Rows | CRS | Indexed |\n"
            output += "|---|---|---|---|\n"
            for tname, info in all_tables.items():
                output += f"| {tname} | {info['rows']:,} | {info['crs']} | {'Yes' if info['has_sindex'] else 'No'} |\n"

        logger.info(f"Spatial stats for '{table_name}': {len(gdf)} points")
        return output


# ===========================================================================
# Tool 6: geo_export
# ===========================================================================

class GeoExportTool(BaseTool):
    """Export a GeoDataFrame to GeoJSON, GeoPackage, Shapefile, or CSV with WKT."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="geo_export",
            description=(
                "Export a loaded geospatial table to a spatial file format. "
                "Supports GeoJSON, GeoPackage (GPKG), Shapefile, or CSV with WKT geometry. "
                "The exported file includes the spatial index for fast loading in GIS tools."
            ),
            category="geo",
            tags=["geo", "spatial", "export", "geojson", "geopackage", "shapefile"],
        ))

    def _execute(
        self,
        table_name: str,
        format: str = "geojson",
        output_path: str = "",
        filename: str = "",
    ) -> str:
        gdf = get_geodataframe(table_name)
        if gdf is None:
            available = ", ".join(list_geodataframes().keys()) or "none"
            return f"Error: Table '{table_name}' not found. Available: {available}"

        if not output_path.strip():
            return "Error: output_path is required."

        fmt = format.lower().strip()
        fname = filename.strip() if filename.strip() else f"spatial_output_{table_name}"

        # Map format to driver and extension
        format_map = {
            "geojson": ("GeoJSON", ".geojson"),
            "geopackage": ("GPKG", ".gpkg"),
            "gpkg": ("GPKG", ".gpkg"),
            "shapefile": ("ESRI Shapefile", ".shp"),
            "shp": ("ESRI Shapefile", ".shp"),
            "csv_with_wkt": (None, ".csv"),
            "csv": (None, ".csv"),
        }

        if fmt not in format_map:
            return f"Error: Unsupported format '{fmt}'. Options: {', '.join(format_map.keys())}"

        driver, ext = format_map[fmt]

        # Ensure filename has correct extension
        if not fname.endswith(ext):
            fname = fname + ext

        # Ensure output directory exists
        os.makedirs(output_path, exist_ok=True)
        full_path = os.path.join(output_path, fname)

        try:
            if driver:
                gdf.to_file(full_path, driver=driver)
            else:
                # CSV with WKT
                export_df = gdf.copy()
                export_df["geometry_wkt"] = gdf.geometry.to_wkt()
                export_df = export_df.drop(columns=["geometry"])
                export_df.to_csv(full_path, index=False)
        except Exception as e:
            return f"Error exporting: {e}"

        # File size
        size_bytes = os.path.getsize(full_path)
        if size_bytes > 1_000_000:
            size_str = f"{size_bytes / 1_000_000:.1f} MB"
        else:
            size_str = f"{size_bytes / 1_000:.1f} KB"

        output = f"## Exported: {table_name}\n\n"
        output += f"- **File:** {full_path}\n"
        output += f"- **Format:** {fmt} ({driver or 'CSV+WKT'})\n"
        output += f"- **Rows:** {len(gdf):,}\n"
        output += f"- **Size:** {size_str}\n"
        output += f"- **CRS:** {gdf.crs}\n"

        logger.info(f"Exported '{table_name}' to {full_path} ({size_str})")
        return output
