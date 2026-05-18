"""Data Export Tools - Export to JSON, CSV, Excel, Parquet, SQLite.

Generic export tools that work with any loaded data.
"""

import json
import sqlite3
from pathlib import Path
from typing import Optional

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.logging import get_logger
from agent_os.tools.library.gwdb_ingest import get_dataframe, list_dataframes, _import_pandas

logger = get_logger(__name__)


def _get_df_or_error(table_name: str):
    df = get_dataframe(table_name)
    if df is None:
        available = ", ".join(list_dataframes().keys()) or "none"
        return None, f"Error: Table '{table_name}' not loaded. Available: {available}"
    return df, None


def _ensure_dir(path: str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# =============================================================================
# Tool 1: gwdb_to_json
# =============================================================================

class GWDBToJSONTool(BaseTool):
    """Export table to JSON file."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_to_json",
            description="Export a loaded table to a JSON file. IMPORTANT: Always pass output_dir from context so files appear in the UI.",
            category="gwdb_export",
            tags=["gwdb", "export", "json"],
        ))

    def _execute(
        self,
        table_name: str,
        file_path: str,
        orient: str = "records",
        indent: int = 2,
        conditions: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        if conditions:
            try:
                df = df.query(conditions)
            except Exception as e:
                return f"Error in filter: {e}"

        if output_dir:
            path = _ensure_dir(str(Path(output_dir) / Path(file_path).name))
        else:
            path = _ensure_dir(file_path)

        try:
            df.to_json(path, orient=orient, indent=indent, force_ascii=False)
            size_mb = path.stat().st_size / 1024 / 1024
            return (
                f"Exported {len(df):,} rows to {path}\n"
                f"Format: JSON ({orient})\n"
                f"File size: {size_mb:.1f} MB"
            )
        except Exception as e:
            return f"Error exporting to JSON: {e}"


# =============================================================================
# Tool 2: gwdb_to_csv
# =============================================================================

class GWDBToCSVTool(BaseTool):
    """Export table to CSV file."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_to_csv",
            description="Export a loaded table to a CSV file. IMPORTANT: Always pass output_dir from context so files appear in the UI.",
            category="gwdb_export",
            tags=["gwdb", "export", "csv"],
        ))

    def _execute(
        self,
        table_name: str,
        file_path: str,
        delimiter: str = ",",
        include_index: bool = False,
        conditions: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        if conditions:
            try:
                df = df.query(conditions)
            except Exception as e:
                return f"Error in filter: {e}"

        if output_dir:
            path = _ensure_dir(str(Path(output_dir) / Path(file_path).name))
        else:
            path = _ensure_dir(file_path)

        try:
            df.to_csv(path, sep=delimiter, index=include_index)
            size_mb = path.stat().st_size / 1024 / 1024
            return (
                f"Exported {len(df):,} rows to {path}\n"
                f"Format: CSV (delimiter='{delimiter}')\n"
                f"File size: {size_mb:.1f} MB"
            )
        except Exception as e:
            return f"Error exporting to CSV: {e}"


# =============================================================================
# Tool 3: gwdb_to_excel
# =============================================================================

class GWDBToExcelTool(BaseTool):
    """Export table to Excel file."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_to_excel",
            description="Export a loaded table to an Excel (.xlsx) file. IMPORTANT: Always pass output_dir from context so files appear in the UI.",
            category="gwdb_export",
            tags=["gwdb", "export", "excel", "xlsx"],
        ))

    def _execute(
        self,
        table_name: str,
        file_path: str,
        sheet_name: str = "Sheet1",
        conditions: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        if conditions:
            try:
                df = df.query(conditions)
            except Exception as e:
                return f"Error in filter: {e}"

        if output_dir:
            path = _ensure_dir(str(Path(output_dir) / Path(file_path).name))
        else:
            path = _ensure_dir(file_path)

        try:
            df.to_excel(path, sheet_name=sheet_name, index=False, engine="openpyxl")
            size_mb = path.stat().st_size / 1024 / 1024
            return (
                f"Exported {len(df):,} rows to {path}\n"
                f"Format: Excel (.xlsx), Sheet: {sheet_name}\n"
                f"File size: {size_mb:.1f} MB"
            )
        except ImportError:
            return "Error: openpyxl not installed. Install with: pip install openpyxl"
        except Exception as e:
            return f"Error exporting to Excel: {e}"


# =============================================================================
# Tool 4: gwdb_to_parquet
# =============================================================================

class GWDBToParquetTool(BaseTool):
    """Export table to Parquet file."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_to_parquet",
            description="Export a loaded table to Parquet format (columnar, compressed). IMPORTANT: Always pass output_dir from context so files appear in the UI.",
            category="gwdb_export",
            tags=["gwdb", "export", "parquet", "columnar"],
        ))

    def _execute(
        self,
        table_name: str,
        file_path: str,
        compression: str = "snappy",
        conditions: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        if conditions:
            try:
                df = df.query(conditions)
            except Exception as e:
                return f"Error in filter: {e}"

        if output_dir:
            path = _ensure_dir(str(Path(output_dir) / Path(file_path).name))
        else:
            path = _ensure_dir(file_path)

        try:
            df.to_parquet(path, compression=compression, index=False)
            size_mb = path.stat().st_size / 1024 / 1024
            return (
                f"Exported {len(df):,} rows to {path}\n"
                f"Format: Parquet (compression={compression})\n"
                f"File size: {size_mb:.1f} MB"
            )
        except ImportError:
            return "Error: pyarrow not installed. Install with: pip install pyarrow"
        except Exception as e:
            return f"Error exporting to Parquet: {e}"


# =============================================================================
# Tool 5: gwdb_to_sqlite
# =============================================================================

class GWDBToSQLiteTool(BaseTool):
    """Export table to SQLite database."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_to_sqlite",
            description="Export a loaded table to a SQLite database file. IMPORTANT: Always pass output_dir from context so files appear in the UI.",
            category="gwdb_export",
            tags=["gwdb", "export", "sqlite", "database"],
        ))

    def _execute(
        self,
        table_name: str,
        db_path: str,
        sql_table_name: Optional[str] = None,
        if_exists: str = "replace",
        conditions: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        if conditions:
            try:
                df = df.query(conditions)
            except Exception as e:
                return f"Error in filter: {e}"

        target_table = sql_table_name or table_name

        if output_dir:
            path = _ensure_dir(str(Path(output_dir) / Path(db_path).name))
        else:
            path = _ensure_dir(db_path)

        try:
            conn = sqlite3.connect(str(path))
            df.to_sql(target_table, conn, if_exists=if_exists, index=False)

            # Verify
            cursor = conn.execute(f"SELECT COUNT(*) FROM [{target_table}]")
            row_count = cursor.fetchone()[0]
            conn.close()

            size_mb = path.stat().st_size / 1024 / 1024
            return (
                f"Exported {len(df):,} rows to {path}\n"
                f"Table: {target_table} ({row_count:,} rows verified)\n"
                f"Mode: {if_exists}\n"
                f"Database size: {size_mb:.1f} MB"
            )
        except Exception as e:
            return f"Error exporting to SQLite: {e}"


# =============================================================================
# Tool 6: gwdb_save_as
# =============================================================================

class GWDBSaveAsTool(BaseTool):
    """Save table with user-specified filename and auto-detected format."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_save_as",
            description=(
                "Save a table with a custom filename. Format auto-detected from extension: "
                ".json, .csv, .xlsx, .parquet, .db/.sqlite. "
                "IMPORTANT: Always pass the output_dir from context so files appear in the UI. "
                "Example: filename='dallam_wells.json', output_dir='/path/to/project/files'"
            ),
            category="gwdb_export",
            tags=["gwdb", "export", "save", "download"],
        ))

    def _execute(
        self,
        table_name: str,
        filename: str,
        conditions: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        if conditions:
            try:
                df = df.query(conditions)
            except Exception as e:
                return f"Error in filter: {e}"

        # Determine output directory
        if output_dir:
            out_path = Path(output_dir) / filename
        else:
            out_path = Path(filename)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        ext = out_path.suffix.lower()

        try:
            if ext == ".json":
                df.to_json(out_path, orient="records", indent=2, force_ascii=False)
            elif ext == ".csv":
                df.to_csv(out_path, index=False)
            elif ext == ".tsv":
                df.to_csv(out_path, sep="\t", index=False)
            elif ext == ".xlsx":
                df.to_excel(out_path, index=False, engine="openpyxl")
            elif ext == ".parquet":
                df.to_parquet(out_path, index=False)
            elif ext in (".db", ".sqlite", ".sqlite3"):
                conn = sqlite3.connect(str(out_path))
                df.to_sql(table_name, conn, if_exists="replace", index=False)
                conn.close()
            elif ext == ".txt":
                df.to_csv(out_path, sep="|", index=False)
            else:
                return f"Error: Unsupported format '{ext}'. Use: .json, .csv, .xlsx, .parquet, .db, .sqlite, .txt"

            size_mb = out_path.stat().st_size / 1024 / 1024
            return (
                f"Saved {len(df):,} rows to {out_path}\n"
                f"Format: {ext} | Size: {size_mb:.1f} MB"
            )
        except ImportError as e:
            return f"Error: Missing dependency — {e}"
        except Exception as e:
            return f"Error saving file: {e}"
