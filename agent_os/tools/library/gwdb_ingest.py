"""Data Ingest Tools - Load files (CSV, TXT, Excel, etc.) into DataFrames.

No hardcoded file formats, delimiters, or domain assumptions.
Auto-detects format from file extension and content.
"""

import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import ToolExecutionError, ErrorCode
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)

# =============================================================================
# Session DataFrame Store (singleton, thread-safe)
# =============================================================================

_store_lock = threading.Lock()
_dataframe_store: Dict[str, Any] = {}  # name -> pandas DataFrame


def get_store() -> Dict[str, Any]:
    return _dataframe_store


def store_dataframe(name: str, df: Any) -> None:
    with _store_lock:
        _dataframe_store[name] = df


def get_dataframe(name: str) -> Any:
    with _store_lock:
        return _dataframe_store.get(name)


def list_dataframes() -> Dict[str, Dict[str, Any]]:
    with _store_lock:
        result = {}
        for name, df in _dataframe_store.items():
            result[name] = {
                "rows": len(df),
                "columns": len(df.columns),
                "column_names": list(df.columns),
                "memory_mb": round(df.memory_usage(deep=True).sum() / 1024 / 1024, 2),
            }
        return result


def _import_pandas():
    try:
        import pandas as pd
        return pd
    except ImportError:
        raise ToolExecutionError(
            "pandas not installed. Install with: pip install pandas",
            error_code=ErrorCode.TOOL_DEPENDENCY_MISSING
        )


# =============================================================================
# Tool 1: gwdb_load_file
# =============================================================================

class GWDBLoadFileTool(BaseTool):
    """Load any data file into a session DataFrame with auto-detection."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_load_file",
            description=(
                "Load a data file into memory. Auto-detects format from extension: "
                ".csv, .tsv, .txt, .xlsx, .xls, .json, .parquet. "
                "For CSV/TXT, auto-detects delimiter (comma, pipe, tab, semicolon). "
                "Override with delimiter parameter if needed. "
                "Returns row/column count and column names."
            ),
            category="gwdb_ingest",
            tags=["gwdb", "ingest", "load", "csv", "txt", "excel", "json", "parquet"],
        ))

    def _execute(
        self,
        file_path: str,
        delimiter: Optional[str] = None,
        name: Optional[str] = None,
        encoding: str = "utf-8",
    ) -> str:
        pd = _import_pandas()
        path = Path(file_path)

        if not path.exists():
            return f"Error: File not found: {file_path}"
        if not path.is_file():
            return f"Error: Not a file: {file_path}"

        ext = path.suffix.lower()

        try:
            if ext in (".xlsx", ".xls"):
                try:
                    df = pd.read_excel(path, engine="openpyxl")
                except ImportError:
                    return "Error: openpyxl not installed. Install with: pip install openpyxl"
            elif ext == ".json":
                df = pd.read_json(path)
            elif ext == ".parquet":
                df = pd.read_parquet(path)
            elif ext in (".csv", ".tsv", ".txt", ""):
                # Auto-detect delimiter if not specified
                if delimiter is None:
                    delimiter = self._detect_delimiter(path)

                try:
                    df = pd.read_csv(
                        path, sep=delimiter, encoding=encoding,
                        low_memory=False, on_bad_lines="warn",
                    )
                except UnicodeDecodeError:
                    df = pd.read_csv(
                        path, sep=delimiter, encoding="latin-1",
                        low_memory=False, on_bad_lines="warn",
                    )
            else:
                # Try as CSV with auto-detect
                if delimiter is None:
                    delimiter = self._detect_delimiter(path)
                try:
                    df = pd.read_csv(
                        path, sep=delimiter, encoding=encoding,
                        low_memory=False, on_bad_lines="warn",
                    )
                except Exception:
                    return f"Error: Unsupported file format '{ext}'. Supported: .csv, .tsv, .txt, .xlsx, .json, .parquet"

            # Clean column names (strip whitespace)
            df.columns = [c.strip() for c in df.columns]

            table_name = name or path.stem
            store_dataframe(table_name, df)

            # Build summary
            dtypes_summary = df.dtypes.value_counts().to_dict()
            dtype_str = ", ".join(f"{v} {k}" for k, v in dtypes_summary.items())

            return (
                f"Loaded '{table_name}': {len(df):,} rows x {len(df.columns)} columns\n"
                f"Columns: {', '.join(df.columns[:15])}"
                f"{'... and ' + str(len(df.columns) - 15) + ' more' if len(df.columns) > 15 else ''}\n"
                f"Types: {dtype_str}\n"
                f"Memory: {df.memory_usage(deep=True).sum() / 1024 / 1024:.1f} MB"
            )
        except Exception as e:
            return f"Error loading file: {e}"

    @staticmethod
    def _detect_delimiter(path: Path) -> str:
        """Read first few lines and detect the most likely delimiter."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                sample = f.read(4096)
        except Exception:
            return ","

        # Count occurrences of common delimiters in the sample
        candidates = {"|": 0, ",": 0, "\t": 0, ";": 0}
        for char, _ in candidates.items():
            candidates[char] = sample.count(char)

        # Pick the most frequent one (if any appear enough)
        best = max(candidates, key=candidates.get)
        if candidates[best] > 0:
            return best
        return ","


# =============================================================================
# Tool 2: gwdb_load_wellmain
# =============================================================================

class GWDBLoadWellMainTool(BaseTool):
    """Load a primary/master data file with auto-detection."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_load_wellmain",
            description=(
                "Load a primary data file with auto-detected delimiter and encoding. "
                "Alias for gwdb_load_file — use this or gwdb_load_file interchangeably. "
                "The table name defaults to the filename stem."
            ),
            category="gwdb_ingest",
            tags=["gwdb", "ingest", "load", "primary"],
        ))

    def _execute(self, file_path: str, name: Optional[str] = None) -> str:
        # Delegate to the generic loader
        loader = GWDBLoadFileTool()
        return loader._execute(file_path=file_path, name=name)


# =============================================================================
# Tool 3: gwdb_load_sql_tables
# =============================================================================

class GWDBLoadSQLTablesTool(BaseTool):
    """Bulk-load all data files from a directory."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_load_sql_tables",
            description=(
                "Bulk-load all data files from a directory into memory. "
                "Supports: .csv, .tsv, .txt, .json, .parquet, .xlsx. "
                "Optionally filter by file pattern (e.g., pattern='*.csv' or pattern='DB_*.txt'). "
                "Each file becomes a table named after its filename stem."
            ),
            category="gwdb_ingest",
            tags=["gwdb", "ingest", "bulk", "directory", "batch"],
        ))

    def _execute(self, directory: str, pattern: str = "*.*") -> str:
        pd = _import_pandas()
        dir_path = Path(directory)

        if not dir_path.exists():
            return f"Error: Directory not found: {directory}"

        supported_exts = {".csv", ".tsv", ".txt", ".json", ".parquet", ".xlsx", ".xls"}
        all_files = sorted(dir_path.glob(pattern))
        data_files = [f for f in all_files if f.suffix.lower() in supported_exts and f.is_file()]

        if not data_files:
            return f"Error: No data files matching '{pattern}' found in {directory}"

        loader = GWDBLoadFileTool()
        loaded = []
        errors = []

        for f in data_files:
            try:
                result = loader._execute(file_path=str(f))
                if result.startswith("Error"):
                    errors.append(f"{f.name}: {result}")
                else:
                    table_name = f.stem
                    df = get_dataframe(table_name)
                    rows = len(df) if df is not None else 0
                    loaded.append(f"{table_name} ({rows:,} rows)")
            except Exception as e:
                errors.append(f"{f.name}: {e}")

        result = f"Loaded {len(loaded)} files from {directory}\n\n"

        if loaded:
            result += "Tables:\n"
            for item in loaded:
                result += f"  - {item}\n"

        if errors:
            result += f"\nErrors ({len(errors)}):\n"
            for err in errors:
                result += f"  - {err}\n"

        return result


# =============================================================================
# Tool 4: gwdb_preview
# =============================================================================

class GWDBPreviewTool(BaseTool):
    """Preview first N rows of a loaded table."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_preview",
            description="Show the first N rows of a loaded table along with shape, dtypes, and null counts. Use after loading a file with gwdb_load_file or gwdb_load_wellmain.",
            category="gwdb_ingest",
            tags=["gwdb", "preview", "head", "sample"],
        ))

    def _execute(self, table_name: str, rows: int = 10) -> str:
        df = get_dataframe(table_name)
        if df is None:
            available = ", ".join(list_dataframes().keys()) or "none"
            return f"Error: Table '{table_name}' not loaded. Available: {available}"

        pd = _import_pandas()

        # Shape info
        result = f"Table: {table_name} ({len(df):,} rows x {len(df.columns)} columns)\n\n"

        # Column info (name, dtype, nulls)
        result += "Column Info:\n"
        for col in df.columns:
            null_count = df[col].isnull().sum()
            null_pct = f" ({null_count / len(df) * 100:.1f}% null)" if null_count > 0 else ""
            result += f"  {col}: {df[col].dtype}{null_pct}\n"

        # Sample rows as markdown table
        result += f"\nFirst {min(rows, len(df))} rows:\n"
        sample = df.head(rows)

        # Truncate wide columns for display
        display_cols = list(df.columns[:12])  # Show max 12 columns
        sample_display = sample[display_cols].copy()
        for col in sample_display.columns:
            sample_display[col] = sample_display[col].astype(str).str[:30]

        result += sample_display.to_markdown(index=False)

        if len(df.columns) > 12:
            result += f"\n\n... {len(df.columns) - 12} more columns not shown"

        return result


# =============================================================================
# Tool 5: gwdb_list_loaded
# =============================================================================

class GWDBListLoadedTool(BaseTool):
    """List all currently loaded DataFrames in the session."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_list_loaded",
            description="List all tables currently loaded in memory with their row counts, column counts, and memory usage.",
            category="gwdb_ingest",
            tags=["gwdb", "list", "status", "session"],
        ))

    def _execute(self) -> str:
        tables = list_dataframes()

        if not tables:
            return "No tables loaded. Use gwdb_load_file or gwdb_load_wellmain to load data."

        result = f"Loaded Tables ({len(tables)}):\n\n"
        total_mem = 0.0
        total_rows = 0

        for name, info in tables.items():
            result += f"  {name}: {info['rows']:,} rows x {info['columns']} cols ({info['memory_mb']} MB)\n"
            total_mem += info["memory_mb"]
            total_rows += info["rows"]

        result += f"\nTotal: {total_rows:,} rows, {total_mem:.1f} MB memory"
        return result
