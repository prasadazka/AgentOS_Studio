"""Data Schema Tools - Schema discovery, table info, lookup values, FK validation.

All schema information is derived dynamically from loaded data.
No hardcoded table names, column names, or domain-specific assumptions.
"""

from typing import Optional

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.logging import get_logger
from agent_os.tools.library.gwdb_ingest import get_dataframe, list_dataframes, _import_pandas

logger = get_logger(__name__)


# =============================================================================
# Tool 1: gwdb_show_schema
# =============================================================================

class GWDBShowSchemaTool(BaseTool):
    """Display schema of all currently loaded tables."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_show_schema",
            description=(
                "Display the schema of all currently loaded tables: table names, "
                "row counts, column names, and data types. Works with any dataset."
            ),
            category="gwdb_schema",
            tags=["gwdb", "schema", "erd", "diagram"],
        ))

    def _execute(self) -> str:
        tables = list_dataframes()

        if not tables:
            return "No tables loaded. Use gwdb_load_file to load data first."

        result = "# Loaded Data Schema\n\n"
        result += f"Tables: {len(tables)}\n\n"

        for name, info in tables.items():
            result += f"## {name}\n"
            result += f"Rows: {info['rows']:,} | Columns: {info['columns']}\n"
            result += f"Memory: {info['memory_mb']} MB\n"
            result += f"Columns: {', '.join(info['column_names'])}\n\n"

        # Show relationships (tables sharing column names)
        if len(tables) > 1:
            result += "## Potential Relationships (shared column names)\n\n"
            all_table_names = list(tables.keys())
            found_links = False
            for i in range(len(all_table_names)):
                for j in range(i + 1, len(all_table_names)):
                    t1, t2 = all_table_names[i], all_table_names[j]
                    cols1 = set(tables[t1]["column_names"])
                    cols2 = set(tables[t2]["column_names"])
                    shared = cols1 & cols2
                    if shared:
                        found_links = True
                        result += f"- **{t1}** <-> **{t2}**: {', '.join(sorted(shared))}\n"
            if not found_links:
                result += "- No shared column names found between tables.\n"

        return result


# =============================================================================
# Tool 2: gwdb_table_info
# =============================================================================

class GWDBTableInfoTool(BaseTool):
    """Show columns, types, and statistics for a loaded table."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_table_info",
            description=(
                "Show detailed information about a loaded table: columns, data types, "
                "non-null counts, and sample values. Works with any loaded dataset."
            ),
            category="gwdb_schema",
            tags=["gwdb", "schema", "table", "columns", "info"],
        ))

    def _execute(self, table_name: str) -> str:
        df = get_dataframe(table_name)
        if df is None:
            available = ", ".join(list_dataframes().keys()) or "none"
            return f"Error: Table '{table_name}' not loaded. Available: {available}"

        result = f"# Table: {table_name}\n\n"
        result += f"Rows: {len(df):,}\n"
        result += f"Columns: {len(df.columns)}\n\n"

        result += "| Column | Type | Non-Null | Null % | Sample Value |\n"
        result += "|--------|------|----------|--------|--------------|\n"
        for col in df.columns:
            dtype = str(df[col].dtype)
            non_null = df[col].notna().sum()
            null_pct = df[col].isnull().mean() * 100
            sample = str(df[col].dropna().iloc[0])[:30] if df[col].notna().any() else "N/A"
            result += f"| {col} | {dtype} | {non_null:,} | {null_pct:.1f}% | {sample} |\n"

        return result


# =============================================================================
# Tool 3: gwdb_lookup_values
# =============================================================================

class GWDBLookupValuesTool(BaseTool):
    """Show all values from a loaded table (useful for reference/lookup tables)."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_lookup_values",
            description=(
                "Show all values from a loaded table. Useful for viewing "
                "reference/lookup tables or small datasets. "
                "Use max_rows to limit output for large tables."
            ),
            category="gwdb_schema",
            tags=["gwdb", "lookup", "reference", "values"],
        ))

    def _execute(self, lookup_table: str, max_rows: int = 50) -> str:
        df = get_dataframe(lookup_table)
        if df is None:
            available = ", ".join(list_dataframes().keys()) or "none"
            return f"Error: Table '{lookup_table}' not loaded. Available: {available}"

        total = len(df)
        display = df.head(max_rows)

        # Truncate wide values
        display_copy = display.copy()
        for col in display_copy.select_dtypes(include=["object"]).columns:
            display_copy[col] = display_copy[col].astype(str).str[:40]

        result = f"Table: {lookup_table}\n"
        result += f"Total entries: {total:,} | Columns: {len(df.columns)}\n\n"
        result += display_copy.to_markdown(index=False)

        if total > max_rows:
            result += f"\n\n... showing {max_rows} of {total:,} entries"

        return result


# =============================================================================
# Tool 4: gwdb_validate_fk
# =============================================================================

class GWDBValidateFKTool(BaseTool):
    """Validate foreign key integrity between two loaded tables."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_validate_fk",
            description=(
                "Validate foreign key integrity: check that all values in a column "
                "of one table exist in a column of another table. "
                "Example: validate that all 'department_id' values in 'employees' "
                "exist in 'departments'."
            ),
            category="gwdb_schema",
            tags=["gwdb", "validate", "fk", "foreign_key", "integrity"],
        ))

    def _execute(
        self,
        data_table: str,
        data_column: str,
        lookup_table: str,
        lookup_column: Optional[str] = None,
    ) -> str:
        data_df = get_dataframe(data_table)
        if data_df is None:
            return f"Error: Table '{data_table}' not loaded."

        lookup_df = get_dataframe(lookup_table)
        if lookup_df is None:
            return f"Error: Table '{lookup_table}' not loaded."

        if data_column not in data_df.columns:
            return f"Error: Column '{data_column}' not found in {data_table}. Available: {', '.join(data_df.columns[:20])}"

        # Auto-detect lookup column (matching name or first column)
        if lookup_column is None:
            if data_column in lookup_df.columns:
                lookup_column = data_column
            else:
                lookup_column = lookup_df.columns[0]

        if lookup_column not in lookup_df.columns:
            return f"Error: Column '{lookup_column}' not found in {lookup_table}. Available: {', '.join(lookup_df.columns[:20])}"

        # Get unique values
        data_values = set(data_df[data_column].dropna().unique())
        lookup_values = set(lookup_df[lookup_column].dropna().unique())

        # Check integrity
        orphans = data_values - lookup_values
        unused = lookup_values - data_values
        valid = data_values & lookup_values

        result = f"FK Validation: {data_table}.{data_column} -> {lookup_table}.{lookup_column}\n\n"
        result += f"Data values: {len(data_values):,}\n"
        result += f"Lookup values: {len(lookup_values):,}\n"
        result += f"Valid (matched): {len(valid):,}\n"
        result += f"Orphaned (no match in lookup): {len(orphans):,}\n"
        result += f"Unused (in lookup but not data): {len(unused):,}\n\n"

        if orphans:
            result += f"Orphaned values (first 20):\n"
            for val in sorted(list(orphans), key=str)[:20]:
                result += f"  - {val}\n"
            if len(orphans) > 20:
                result += f"  ... and {len(orphans) - 20} more\n"

        if not orphans:
            result += "FK integrity: PASSED -- all data values exist in lookup table."
        else:
            pct = len(orphans) / len(data_values) * 100
            result += f"\nFK integrity: FAILED -- {pct:.1f}% of values have no match in lookup."

        return result
