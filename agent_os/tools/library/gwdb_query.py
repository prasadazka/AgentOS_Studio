"""Data Query Tools - Filter, count, aggregate, search, SQL.

Generic query tools that work with any loaded data. No domain-specific assumptions.
"""

from typing import Any, Dict, List, Optional

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import ToolExecutionError, ErrorCode
from agent_os.utils.logging import get_logger
from agent_os.tools.library.gwdb_ingest import get_dataframe, list_dataframes, _import_pandas

logger = get_logger(__name__)


def _get_df_or_error(table_name: str):
    """Get DataFrame or return error string."""
    df = get_dataframe(table_name)
    if df is None:
        available = ", ".join(list_dataframes().keys()) or "none"
        return None, f"Error: Table '{table_name}' not loaded. Available: {available}"
    return df, None


# =============================================================================
# Tool 1: gwdb_filter
# =============================================================================

class GWDBFilterTool(BaseTool):
    """Filter rows by column conditions."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_filter",
            description=(
                "Filter rows in a loaded table by pandas query conditions. "
                "Examples: conditions='column_name == \"value\"', conditions='amount > 300', "
                "conditions='status == \"active\" and category == \"A\"'. "
                "Returns matching rows as a table."
            ),
            category="gwdb_query",
            tags=["gwdb", "filter", "where", "query"],
        ))

    def _execute(
        self,
        table_name: str,
        conditions: str,
        columns: Optional[str] = None,
        max_rows: int = 50,
    ) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        try:
            filtered = df.query(conditions)
        except Exception as e:
            return f"Error in filter expression: {e}\nAvailable columns: {', '.join(df.columns[:20])}"

        # Select specific columns if requested
        if columns:
            col_list = [c.strip() for c in columns.split(",")]
            missing = [c for c in col_list if c not in filtered.columns]
            if missing:
                return f"Error: Columns not found: {missing}. Available: {', '.join(df.columns)}"
            filtered = filtered[col_list]

        total = len(filtered)
        display = filtered.head(max_rows)

        # Truncate wide values for display
        display_copy = display.copy()
        for col in display_copy.select_dtypes(include=["object"]).columns:
            display_copy[col] = display_copy[col].astype(str).str[:40]

        result = f"Found {total:,} rows matching: {conditions}\n\n"
        result += display_copy.to_markdown(index=False)

        if total > max_rows:
            result += f"\n\n... showing {max_rows} of {total:,} rows"

        return result


# =============================================================================
# Tool 2: gwdb_count
# =============================================================================

class GWDBCountTool(BaseTool):
    """Count rows matching criteria."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_count",
            description=(
                "Count rows in a loaded table, optionally filtered by conditions. "
                "Examples: table_name='my_data' (total count), "
                "conditions='status == \"active\"' (filtered count)."
            ),
            category="gwdb_query",
            tags=["gwdb", "count", "total"],
        ))

    def _execute(self, table_name: str, conditions: Optional[str] = None) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        if conditions:
            try:
                filtered = df.query(conditions)
                return f"{len(filtered):,} rows match: {conditions} (out of {len(df):,} total)"
            except Exception as e:
                return f"Error in condition: {e}"
        else:
            return f"{len(df):,} total rows in {table_name}"


# =============================================================================
# Tool 3: gwdb_aggregate
# =============================================================================

class GWDBAggregateTool(BaseTool):
    """Group by and aggregate data."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_aggregate",
            description=(
                "Group data by one or more columns and compute aggregates. "
                "group_by: comma-separated column names (e.g., 'category' or 'region,status'). "
                "agg_column: column to aggregate (e.g., 'amount'). "
                "agg_func: 'count', 'mean', 'sum', 'min', 'max', 'median' (default: 'count'). "
                "Example: group_by='category', agg_func='count' -> items per category."
            ),
            category="gwdb_query",
            tags=["gwdb", "aggregate", "group", "stats"],
        ))

    def _execute(
        self,
        table_name: str,
        group_by: str,
        agg_column: Optional[str] = None,
        agg_func: str = "count",
        top_n: int = 30,
        sort_desc: bool = True,
    ) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        group_cols = [c.strip() for c in group_by.split(",")]
        missing = [c for c in group_cols if c not in df.columns]
        if missing:
            return f"Error: Columns not found: {missing}"

        try:
            if agg_func == "count":
                result_df = df.groupby(group_cols).size().reset_index(name="count")
            else:
                if not agg_column:
                    return "Error: agg_column required for non-count aggregations"
                if agg_column not in df.columns:
                    return f"Error: Column '{agg_column}' not found"

                result_df = df.groupby(group_cols)[agg_column].agg(agg_func).reset_index()
                result_df.columns = list(group_cols) + [f"{agg_func}_{agg_column}"]

            # Sort
            sort_col = result_df.columns[-1]
            result_df = result_df.sort_values(sort_col, ascending=not sort_desc)

            total = len(result_df)
            display = result_df.head(top_n)

            output = f"Aggregation: {agg_func} by {group_by} ({total:,} groups)\n\n"
            output += display.to_markdown(index=False)

            if total > top_n:
                output += f"\n\n... showing top {top_n} of {total:,} groups"

            return output
        except Exception as e:
            return f"Error in aggregation: {e}"


# =============================================================================
# Tool 4: gwdb_search
# =============================================================================

class GWDBSearchTool(BaseTool):
    """Full-text search across all text columns."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_search",
            description=(
                "Search for a text term across all text columns in a table. "
                "Case-insensitive. Returns rows where any text column contains the search term."
            ),
            category="gwdb_query",
            tags=["gwdb", "search", "find", "text"],
        ))

    def _execute(
        self,
        table_name: str,
        term: str,
        max_rows: int = 30,
    ) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        text_cols = df.select_dtypes(include=["object"]).columns.tolist()
        if not text_cols:
            return "Error: No text columns found to search"

        mask = df[text_cols].apply(
            lambda col: col.astype(str).str.contains(term, case=False, na=False)
        ).any(axis=1)

        matches = df[mask]
        total = len(matches)

        if total == 0:
            return f"No rows found containing '{term}'"

        display = matches.head(max_rows)
        # Show a subset of columns for readability
        show_cols = list(df.columns[:10])
        display_sub = display[show_cols].copy()
        for col in display_sub.select_dtypes(include=["object"]).columns:
            display_sub[col] = display_sub[col].astype(str).str[:35]

        result = f"Found {total:,} rows containing '{term}'\n\n"
        result += display_sub.to_markdown(index=False)

        if total > max_rows:
            result += f"\n\n... showing {max_rows} of {total:,} matches"

        return result


# =============================================================================
# Tool 5: gwdb_describe_column
# =============================================================================

class GWDBDescribeColumnTool(BaseTool):
    """Get statistics and value distribution for a column."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_describe_column",
            description=(
                "Get detailed statistics for a specific column: unique values, "
                "null count, min/max/mean (numeric), or top value counts (text). "
                "Useful for understanding data distribution before querying."
            ),
            category="gwdb_query",
            tags=["gwdb", "describe", "stats", "column", "distribution"],
        ))

    def _execute(
        self,
        table_name: str,
        column: str,
        top_n: int = 20,
    ) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        if column not in df.columns:
            return f"Error: Column '{column}' not found. Available: {', '.join(df.columns)}"

        col = df[column]
        result = f"Column: {column}\n"
        result += f"Type: {col.dtype}\n"
        result += f"Total rows: {len(col):,}\n"
        result += f"Non-null: {col.notna().sum():,}\n"
        result += f"Null: {col.isnull().sum():,} ({col.isnull().mean() * 100:.1f}%)\n"
        result += f"Unique values: {col.nunique():,}\n\n"

        pd = _import_pandas()

        # Numeric stats
        if pd.api.types.is_numeric_dtype(col):
            result += "Numeric Statistics:\n"
            result += f"  Min: {col.min()}\n"
            result += f"  Max: {col.max()}\n"
            result += f"  Mean: {col.mean():.2f}\n"
            result += f"  Median: {col.median():.2f}\n"
            result += f"  Std: {col.std():.2f}\n"
            result += f"  25th percentile: {col.quantile(0.25):.2f}\n"
            result += f"  75th percentile: {col.quantile(0.75):.2f}\n"
        else:
            # Categorical value counts
            result += f"Top {min(top_n, col.nunique())} values:\n"
            counts = col.value_counts().head(top_n)
            for val, count in counts.items():
                pct = count / len(df) * 100
                result += f"  {val}: {count:,} ({pct:.1f}%)\n"

        return result


# =============================================================================
# Tool 6: gwdb_sql_query
# =============================================================================

class GWDBSQLQueryTool(BaseTool):
    """Run SQL queries on loaded DataFrames via DuckDB."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_sql_query",
            description=(
                "Run SQL queries against loaded tables using DuckDB. "
                "All loaded tables are available as SQL tables by their name. "
                "Example: query='SELECT category, COUNT(*) as cnt FROM my_data GROUP BY category ORDER BY cnt DESC LIMIT 10'. "
                "Supports full SQL: JOINs, WHERE, GROUP BY, HAVING, subqueries, window functions."
            ),
            category="gwdb_query",
            tags=["gwdb", "sql", "duckdb", "query"],
        ))

    def _execute(self, query: str, max_rows: int = 100) -> str:
        try:
            import duckdb
        except ImportError:
            return "Error: duckdb not installed. Install with: pip install duckdb"

        pd = _import_pandas()
        tables = list_dataframes()
        if not tables:
            return "Error: No tables loaded. Load data first with gwdb_load_file."

        # Basic SQL injection check
        query_upper = query.upper().strip()
        dangerous = ["DROP ", "DELETE ", "TRUNCATE ", "ALTER ", "INSERT ", "UPDATE ", "CREATE "]
        for d in dangerous:
            if d in query_upper:
                return f"Error: Destructive SQL not allowed ({d.strip()}). Use read-only queries."

        try:
            conn = duckdb.connect(":memory:")

            # Register all loaded DataFrames as tables
            for name, _ in tables.items():
                df = get_dataframe(name)
                conn.register(name, df)

            result_df = conn.execute(query).fetchdf()
            conn.close()

            total = len(result_df)
            display = result_df.head(max_rows)

            # Truncate wide values
            display_copy = display.copy()
            for col in display_copy.select_dtypes(include=["object"]).columns:
                display_copy[col] = display_copy[col].astype(str).str[:40]

            output = f"Query returned {total:,} rows\n\n"
            output += display_copy.to_markdown(index=False)

            if total > max_rows:
                output += f"\n\n... showing {max_rows} of {total:,} rows"

            return output
        except Exception as e:
            table_list = ", ".join(tables.keys())
            return f"SQL Error: {e}\nAvailable tables: {table_list}"
