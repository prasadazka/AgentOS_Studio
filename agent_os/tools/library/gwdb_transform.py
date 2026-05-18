"""Data Transform Tools - Create derived tables via SQL.

Execute SQL SELECT queries (with JOINs, CASTs, NULLs) and store the result
as a new in-memory table. Fully dynamic — no hardcoded table or column names.
"""

from typing import Optional

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.logging import get_logger
from agent_os.tools.library.gwdb_ingest import (
    get_dataframe,
    list_dataframes,
    store_dataframe,
    _import_pandas,
)

logger = get_logger(__name__)


def _detect_quality_warnings(result_df, total_rows):
    """Detect common data quality issues that indicate the SQL query was wrong.

    Returns a list of warning strings. These are shown to the agent so it can
    self-correct before the user sees bad output.
    """
    warnings = []
    pd = _import_pandas()

    for col in result_df.columns:
        null_count = result_df[col].isnull().sum()
        null_pct = null_count / total_rows * 100 if total_rows > 0 else 0

        # Warn if a column ending in "Id" is 100% null — likely a failed JOIN
        if col.endswith("Id") and null_pct == 100:
            warnings.append(
                f"CRITICAL: Column '{col}' is 100% NULL. This is a Foreign Key column "
                f"(ends in 'Id') — you likely forgot to JOIN the lookup table. "
                f"Load the lookup table with gwdb_load_file and re-run with a proper JOIN."
            )

        # Warn if a column ending in "Id" contains text instead of numeric IDs
        elif col.endswith("Id") and null_pct < 100:
            non_null = result_df[col].dropna()
            if len(non_null) > 0:
                dtype = non_null.dtype
                if dtype == "object":
                    # Check if values are text strings (not numeric)
                    sample = non_null.head(10)
                    has_text = any(
                        isinstance(v, str) and not v.strip().replace("-", "").isdigit()
                        for v in sample
                    )
                    if has_text:
                        sample_vals = list(non_null.head(3))
                        warnings.append(
                            f"CRITICAL: Column '{col}' contains text values {sample_vals} "
                            f"but Foreign Key columns must contain numeric IDs. "
                            f"You need to JOIN a lookup table to resolve text names "
                            f"to their numeric IDs."
                        )

        # Warn if an "Id" column has same values as a known source column
        # (e.g., using StateWellNumber as StateWellId)
        if col.endswith("Id") and null_pct < 100:
            non_null = result_df[col].dropna()
            if len(non_null) > 0 and pd.api.types.is_numeric_dtype(non_null):
                min_val = non_null.min()
                max_val = non_null.max()
                # If supposed to be a sequential FK (1, 2, 3, ...) but values are large
                # numbers (like well numbers 140301+), warn about wrong mapping
                if col == result_df.columns[0] and min_val > 10000:
                    warnings.append(
                        f"WARNING: Column '{col}' starts at {int(min_val)} — if this is "
                        f"supposed to be a sequential primary/foreign key (1, 2, 3, ...), "
                        f"you may be using the wrong source column. Check if you need "
                        f"to JOIN a mapping table to get the correct ID."
                    )

    return warnings


class GWDBCreateTableTool(BaseTool):
    """Execute a SQL SELECT and store the result as a new in-memory table."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_create_table",
            description=(
                "Execute a SQL SELECT query and store the result as a new in-memory table. "
                "Use this to build derived/normalized tables from loaded data using JOINs, "
                "NULL AS, CAST, subqueries, etc. All loaded tables are available as SQL tables. "
                "IMPORTANT: For Foreign Key columns (ending in 'Id'), you MUST JOIN the "
                "lookup table to resolve text values to numeric IDs. Do NOT pass text "
                "values for FK columns. Use NULL AS col_name for columns with no source data. "
                "Example: query='SELECT d.StateWellId, c.CountyId, NULL AS Address, "
                "s.Elevation FROM source s JOIN data_table d ON s.key = d.key "
                "LEFT JOIN LU_County c ON UPPER(s.County) = c.CountyName', "
                "table_name='target_table', "
                "expected_columns='StateWellId,CountyId,Address,Elevation'. "
                "The result is stored in memory for export with gwdb_to_csv, gwdb_save_as, etc."
            ),
            category="gwdb_transform",
            tags=["gwdb", "transform", "create", "join", "sql", "derive"],
        ))

    def _execute(
        self,
        query: str,
        table_name: str,
        expected_columns: Optional[str] = None,
        if_exists: str = "replace",
    ) -> str:
        """Execute SQL and store result as a new table.

        Args:
            query: SQL SELECT query (JOINs, NULL AS, CAST, subqueries supported).
            table_name: Name for the new in-memory table.
            expected_columns: Comma-separated column names for schema validation (optional).
            if_exists: 'replace' (default) overwrites existing table, 'error' raises if exists.
        """
        try:
            import duckdb
        except ImportError:
            return "Error: duckdb not installed. Install with: pip install duckdb"

        pd = _import_pandas()

        # Validate table_name
        if not table_name or not table_name.strip():
            return "Error: table_name is required."
        table_name = table_name.strip()

        # Check if_exists policy
        existing = list_dataframes()
        if if_exists == "error" and table_name in existing:
            return (
                f"Error: Table '{table_name}' already exists and if_exists='error'. "
                f"Use if_exists='replace' to overwrite."
            )

        if not existing:
            return "Error: No tables loaded. Load data first with gwdb_load_file."

        # SQL safety check — block destructive statements
        query_upper = query.upper().strip()
        dangerous = ["DROP ", "DELETE ", "TRUNCATE ", "ALTER ", "INSERT ", "UPDATE "]
        for d in dangerous:
            if d in query_upper:
                return f"Error: Destructive SQL not allowed ({d.strip()}). Only SELECT queries are supported."

        # Also block CREATE TABLE — this tool handles table creation via store
        if query_upper.startswith("CREATE "):
            return "Error: Use a SELECT query. The tool handles table creation automatically."

        try:
            conn = duckdb.connect(":memory:")

            # Register ALL loaded DataFrames as SQL tables
            for name, _ in existing.items():
                df = get_dataframe(name)
                if df is not None:
                    conn.register(name, df)

            # Execute the query
            result_df = conn.execute(query).fetchdf()
            conn.close()

            total_rows = len(result_df)
            total_cols = len(result_df.columns)

            if total_rows == 0:
                return (
                    f"Warning: Query returned 0 rows. Table '{table_name}' was NOT created.\n"
                    f"Check your JOIN conditions and column names.\n"
                    f"Available tables: {', '.join(existing.keys())}"
                )

            # Store the result as a new in-memory table
            store_dataframe(table_name, result_df)

            # Build response
            output = f"Created table **{table_name}** with {total_rows:,} rows and {total_cols} columns.\n\n"

            # ============================================================
            # Quality warnings — detect common mistakes BEFORE showing data
            # ============================================================
            quality_warnings = _detect_quality_warnings(result_df, total_rows)
            if quality_warnings:
                output += "## DATA QUALITY WARNINGS -- ACTION REQUIRED\n\n"
                for w in quality_warnings:
                    output += f"- {w}\n"
                output += (
                    "\n**The table was created but likely has INCORRECT data. "
                    "You should fix the issues above and re-run gwdb_create_table "
                    "with a corrected SQL query.**\n\n"
                )

            # Schema summary
            output += "## Schema\n\n"
            output += "| Column | Type |\n"
            output += "|--------|------|\n"
            for col in result_df.columns:
                output += f"| {col} | {result_df[col].dtype} |\n"
            output += "\n"

            # Schema validation (if expected_columns provided)
            if expected_columns:
                expected = [c.strip() for c in expected_columns.split(",") if c.strip()]
                actual = list(result_df.columns)

                missing = [c for c in expected if c not in actual]
                extra = [c for c in actual if c not in expected]
                matched = [c for c in expected if c in actual]

                if not missing and not extra:
                    output += f"**Schema Validation: PASSED** ({len(matched)}/{len(expected)} columns match)\n\n"
                else:
                    output += f"**Schema Validation: FAILED**\n"
                    output += f"- Matched: {len(matched)}/{len(expected)}\n"
                    if missing:
                        output += f"- **MISSING columns** (must be added): {', '.join(missing)}\n"
                    if extra:
                        output += f"- Unexpected columns: {', '.join(extra)}\n"
                    output += (
                        "\n**Re-run with a corrected query that includes ALL expected columns. "
                        "Use NULL AS column_name for columns with no source data.**\n\n"
                    )
            else:
                # No expected_columns provided — warn about it
                output += (
                    "**Note:** No expected_columns provided. Pass expected_columns to "
                    "validate the output schema matches the target table definition.\n\n"
                )

            # Sample rows (first 5)
            sample = result_df.head(5).copy()
            for col in sample.select_dtypes(include=["object"]).columns:
                sample[col] = sample[col].astype(str).str[:40]

            output += "## Sample (first 5 rows)\n\n"
            output += sample.to_markdown(index=False)
            output += "\n\n"

            # Null summary for awareness
            null_counts = result_df.isnull().sum()
            cols_with_nulls = null_counts[null_counts > 0]
            if len(cols_with_nulls) > 0:
                output += "## Null Values\n\n"
                for col, count in cols_with_nulls.items():
                    pct = count / total_rows * 100
                    output += f"- {col}: {count:,} nulls ({pct:.1f}%)\n"
                output += "\n"

            output += f"Table '{table_name}' is now available for export (gwdb_to_csv, gwdb_save_as) or further querying."

            logger.info(
                f"Created table '{table_name}': {total_rows:,} rows, {total_cols} columns, "
                f"warnings={len(quality_warnings)}"
            )

            return output

        except Exception as e:
            table_list = ", ".join(existing.keys())
            return (
                f"SQL Error: {e}\n"
                f"Available tables: {table_list}\n\n"
                f"Tip: Check column names with gwdb_table_info(table_name) "
                f"and verify JOIN conditions."
            )
