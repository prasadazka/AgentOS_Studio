"""Data export and format conversion tools"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Literal, Union
from datetime import datetime

from pydantic import BaseModel, Field, validator
import pandas as pd

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import ToolExecutionError, ToolValidationError, ErrorCode
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# TOOL 1: CSV to SQLite (with smart schema detection)
# =============================================================================

class CSVToSQLiteOutput(BaseModel):
    """Output for CSV to SQLite operation"""
    success: bool
    operation: str = "csv_to_sqlite"
    source_file: str
    database_path: str
    table_name: str
    rows_imported: int = 0
    columns_created: int = 0
    table_schema: Optional[Dict[str, str]] = None
    data_cleaning: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class CSVToSQLiteTool(BaseTool):
    """
    Import CSV to SQLite with smart schema detection and data cleaning.

    Features:
    - Auto-detect column types (int, float, text, date)
    - Clean data before import (handle nulls, trim whitespace)
    - Create table with proper schema
    - Support append or replace modes
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="csv_to_sqlite",
                description="Import CSV file to SQLite database with automatic schema detection. Cleans data and creates proper column types (INTEGER, REAL, TEXT, DATE).",
                category="data_export",
                tags=["csv", "sqlite", "import", "etl", "database"]
            )
        )

    def _detect_column_type(self, series: pd.Series) -> str:
        """Detect SQLite column type from pandas series"""
        # Drop nulls for detection
        non_null = series.dropna()

        if len(non_null) == 0:
            return "TEXT"

        # Check if already numeric
        if pd.api.types.is_integer_dtype(series):
            return "INTEGER"
        if pd.api.types.is_float_dtype(series):
            return "REAL"

        # Try to infer from string values
        sample = non_null.head(100).astype(str)

        # Try integer
        try:
            sample.astype(int)
            return "INTEGER"
        except (ValueError, TypeError):
            pass

        # Try float
        try:
            sample.astype(float)
            return "REAL"
        except (ValueError, TypeError):
            pass

        # Try date
        try:
            pd.to_datetime(sample, format='mixed', dayfirst=False)
            # Check if looks like date
            if any(c in str(non_null.iloc[0]) for c in ['-', '/', ':']):
                return "TEXT"  # Store dates as TEXT in SQLite
        except:
            pass

        return "TEXT"

    def _clean_column_name(self, name: str) -> str:
        """Clean column name for SQLite compatibility"""
        import re
        # Replace spaces and special chars with underscore
        clean = re.sub(r'[^\w]', '_', str(name))
        # Remove leading numbers
        if clean[0].isdigit():
            clean = '_' + clean
        return clean.lower()

    def _execute(
        self,
        csv_path: str,
        database_path: str,
        table_name: Optional[str] = None,
        if_exists: str = "replace",  # replace, append, fail
        clean_data: bool = True,
        detect_types: bool = True,
    ) -> str:
        """
        Import CSV to SQLite with smart schema.

        Args:
            csv_path: Path to CSV file
            database_path: Path to SQLite database (created if not exists)
            table_name: Table name (defaults to CSV filename)
            if_exists: What to do if table exists (replace/append/fail)
            clean_data: Clean data before import (trim whitespace, handle nulls)
            detect_types: Auto-detect column types

        Returns:
            JSON with import results
        """
        start_time = time.time()
        cleaning_stats = {}

        try:
            # Validate paths
            csv_file = Path(csv_path)
            if not csv_file.exists():
                return CSVToSQLiteOutput(
                    success=False,
                    source_file=csv_path,
                    database_path=database_path,
                    table_name=table_name or "",
                    error=f"CSV file not found: {csv_path}",
                    error_code=ErrorCode.FILE_NOT_FOUND.value
                ).to_json()

            # Default table name from filename
            if not table_name:
                table_name = csv_file.stem.lower().replace(' ', '_').replace('-', '_')

            # Read CSV
            logger.info(f"Reading CSV: {csv_path}")
            df = pd.read_csv(csv_path)
            original_rows = len(df)
            original_cols = len(df.columns)

            # Clean column names
            df.columns = [self._clean_column_name(c) for c in df.columns]

            # Data cleaning
            if clean_data:
                # Trim whitespace from string columns
                string_cols = df.select_dtypes(include=['object']).columns
                for col in string_cols:
                    df[col] = df[col].astype(str).str.strip()
                    # Replace 'nan' strings with None
                    df[col] = df[col].replace(['nan', 'None', 'NULL', ''], None)

                cleaning_stats['whitespace_trimmed'] = len(string_cols)
                cleaning_stats['null_strings_replaced'] = True

            # Detect and create schema
            schema = {}
            if detect_types:
                for col in df.columns:
                    schema[col] = self._detect_column_type(df[col])
            else:
                schema = {col: "TEXT" for col in df.columns}

            # Create database and table
            db_path = Path(database_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)

            conn = sqlite3.connect(database_path)

            # Handle if_exists
            if if_exists == "replace":
                conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            elif if_exists == "fail":
                cursor = conn.execute(
                    f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'"
                )
                if cursor.fetchone():
                    conn.close()
                    return CSVToSQLiteOutput(
                        success=False,
                        source_file=csv_path,
                        database_path=database_path,
                        table_name=table_name,
                        error=f"Table '{table_name}' already exists",
                        error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                    ).to_json()

            # Create table with schema (if not append)
            if if_exists != "append":
                cols_def = ", ".join([f"{col} {dtype}" for col, dtype in schema.items()])
                create_sql = f"CREATE TABLE IF NOT EXISTS {table_name} ({cols_def})"
                conn.execute(create_sql)
                logger.info(f"Created table: {table_name}")

            # Import data
            df.to_sql(table_name, conn, if_exists="append" if if_exists == "append" else "replace", index=False)

            # Verify import
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
            rows_imported = cursor.fetchone()[0]

            conn.close()

            duration = time.time() - start_time

            return CSVToSQLiteOutput(
                success=True,
                source_file=csv_path,
                database_path=database_path,
                table_name=table_name,
                rows_imported=rows_imported,
                columns_created=len(schema),
                table_schema=schema,
                data_cleaning={
                    **cleaning_stats,
                    "original_rows": original_rows,
                    "duration_seconds": round(duration, 2)
                }
            ).to_json()

        except Exception as e:
            logger.error(f"CSV to SQLite failed: {e}", exc_info=True)
            return CSVToSQLiteOutput(
                success=False,
                source_file=csv_path,
                database_path=database_path,
                table_name=table_name or "",
                error=str(e),
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


# =============================================================================
# TOOL 2: Format Converter (CSV ↔ JSON ↔ Excel)
# =============================================================================

class DataFormatConverterOutput(BaseModel):
    """Output for format conversion"""
    success: bool
    operation: str = "format_convert"
    source_file: str
    output_file: str
    source_format: str
    output_format: str
    rows_converted: int = 0
    file_size_bytes: int = 0
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class DataFormatConverterTool(BaseTool):
    """
    Convert data between formats: CSV, JSON, Excel, Parquet.

    Supported conversions:
    - CSV → JSON, Excel, Parquet
    - JSON → CSV, Excel, Parquet
    - Excel → CSV, JSON, Parquet
    - Parquet → CSV, JSON, Excel
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="data_format_convert",
                description="Convert data files between formats: CSV, JSON, Excel (.xlsx), Parquet. Auto-detects source format from extension.",
                category="data_export",
                tags=["convert", "csv", "json", "excel", "parquet", "export"]
            )
        )

    def _read_file(self, file_path: str) -> pd.DataFrame:
        """Read file based on extension"""
        path = Path(file_path)
        ext = path.suffix.lower()

        if ext == '.csv':
            return pd.read_csv(file_path)
        elif ext == '.json':
            return pd.read_json(file_path)
        elif ext in ['.xlsx', '.xls']:
            return pd.read_excel(file_path)
        elif ext == '.parquet':
            return pd.read_parquet(file_path)
        else:
            raise ToolValidationError(f"Unsupported source format: {ext}", field_name="source_file")

    def _write_file(self, df: pd.DataFrame, file_path: str, output_format: str) -> int:
        """Write DataFrame to file, return file size"""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        fmt = output_format.lower().strip('.')

        if fmt == 'csv':
            df.to_csv(file_path, index=False)
        elif fmt == 'json':
            df.to_json(file_path, orient='records', indent=2, date_format='iso')
        elif fmt in ['xlsx', 'excel']:
            df.to_excel(file_path, index=False, engine='openpyxl')
        elif fmt == 'parquet':
            df.to_parquet(file_path, index=False)
        else:
            raise ToolValidationError(f"Unsupported output format: {fmt}", field_name="output_format")

        return path.stat().st_size

    def _execute(
        self,
        source_file: str,
        output_format: str,
        output_file: Optional[str] = None,
    ) -> str:
        """
        Convert data file to another format.

        Args:
            source_file: Path to source file (CSV, JSON, Excel, Parquet)
            output_format: Target format (csv, json, xlsx, parquet)
            output_file: Output path (optional, defaults to same name with new extension)

        Returns:
            JSON with conversion results
        """
        try:
            source_path = Path(source_file)

            if not source_path.exists():
                return DataFormatConverterOutput(
                    success=False,
                    source_file=source_file,
                    output_file=output_file or "",
                    source_format=source_path.suffix,
                    output_format=output_format,
                    error=f"Source file not found: {source_file}",
                    error_code=ErrorCode.FILE_NOT_FOUND.value
                ).to_json()

            source_format = source_path.suffix.lower()

            # Determine output path
            fmt = output_format.lower().strip('.')
            if fmt == 'excel':
                fmt = 'xlsx'

            if not output_file:
                output_file = str(source_path.with_suffix(f'.{fmt}'))

            # Read source
            logger.info(f"Reading {source_format}: {source_file}")
            df = self._read_file(source_file)
            rows = len(df)

            # Write output
            logger.info(f"Writing {fmt}: {output_file}")
            file_size = self._write_file(df, output_file, fmt)

            return DataFormatConverterOutput(
                success=True,
                source_file=source_file,
                output_file=output_file,
                source_format=source_format,
                output_format=f".{fmt}",
                rows_converted=rows,
                file_size_bytes=file_size
            ).to_json()

        except ToolValidationError as e:
            return DataFormatConverterOutput(
                success=False,
                source_file=source_file,
                output_file=output_file or "",
                source_format=Path(source_file).suffix if source_file else "",
                output_format=output_format,
                error=str(e),
                error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
            ).to_json()

        except Exception as e:
            logger.error(f"Format conversion failed: {e}", exc_info=True)
            return DataFormatConverterOutput(
                success=False,
                source_file=source_file,
                output_file=output_file or "",
                source_format=Path(source_file).suffix if source_file else "",
                output_format=output_format,
                error=str(e),
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


# =============================================================================
# TOOL 3: SQLite to CSV Export
# =============================================================================

class SQLiteToCSVOutput(BaseModel):
    """Output for SQLite to CSV export"""
    success: bool
    operation: str = "sqlite_to_csv"
    database_path: str
    table_name: str
    output_file: str
    rows_exported: int = 0
    columns: List[str] = []
    file_size_bytes: int = 0
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class SQLiteToCSVTool(BaseTool):
    """Export SQLite table to CSV file"""

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="sqlite_to_csv",
                description="Export SQLite table to CSV file. Can export full table or custom query results.",
                category="data_export",
                tags=["sqlite", "csv", "export", "database"]
            )
        )

    def _execute(
        self,
        database_path: str,
        table_name: str,
        output_file: Optional[str] = None,
        query: Optional[str] = None,
    ) -> str:
        """
        Export SQLite table to CSV.

        Args:
            database_path: Path to SQLite database
            table_name: Table to export
            output_file: Output CSV path (optional)
            query: Custom SQL query (optional, overrides table_name)

        Returns:
            JSON with export results
        """
        try:
            db_path = Path(database_path)
            if not db_path.exists():
                return SQLiteToCSVOutput(
                    success=False,
                    database_path=database_path,
                    table_name=table_name,
                    output_file=output_file or "",
                    error=f"Database not found: {database_path}",
                    error_code=ErrorCode.FILE_NOT_FOUND.value
                ).to_json()

            # Default output path
            if not output_file:
                output_file = str(db_path.parent / f"{table_name}.csv")

            conn = sqlite3.connect(database_path)

            # Use custom query or select all from table
            sql = query if query else f"SELECT * FROM {table_name}"

            logger.info(f"Executing: {sql[:100]}...")
            df = pd.read_sql_query(sql, conn)
            conn.close()

            # Write CSV
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(output_file, index=False)

            return SQLiteToCSVOutput(
                success=True,
                database_path=database_path,
                table_name=table_name,
                output_file=output_file,
                rows_exported=len(df),
                columns=list(df.columns),
                file_size_bytes=output_path.stat().st_size
            ).to_json()

        except Exception as e:
            logger.error(f"SQLite to CSV failed: {e}", exc_info=True)
            return SQLiteToCSVOutput(
                success=False,
                database_path=database_path,
                table_name=table_name,
                output_file=output_file or "",
                error=str(e),
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()
