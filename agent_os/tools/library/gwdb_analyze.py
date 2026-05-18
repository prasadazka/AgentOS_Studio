"""Data Analysis Tools - Quality checks, profiling, diagnostics.

All analysis is dynamic based on loaded data. No hardcoded column names or domain assumptions.
"""

from typing import Any, Dict, List, Optional

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


# =============================================================================
# Tool 1: gwdb_missing_values
# =============================================================================

class GWDBMissingValuesTool(BaseTool):
    """Report missing/null values per column."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_missing_values",
            description="Report missing/null values for each column in a table. Shows count, percentage, and highlights columns with >5% missing data.",
            category="gwdb_analyze",
            tags=["gwdb", "missing", "null", "quality"],
        ))

    def _execute(self, table_name: str, threshold_pct: float = 0.0) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        total = len(df)
        null_counts = df.isnull().sum()
        null_pcts = (null_counts / total * 100).round(2)

        # Filter by threshold
        mask = null_pcts >= threshold_pct
        report_cols = null_counts[mask].sort_values(ascending=False)

        result = f"Missing Values Report: {table_name} ({total:,} rows)\n\n"

        if report_cols.empty:
            return result + "No missing values found!"

        cols_with_nulls = (null_counts > 0).sum()
        result += f"Columns with nulls: {cols_with_nulls} / {len(df.columns)}\n\n"

        result += "| Column | Missing | Percentage | Severity |\n"
        result += "|--------|---------|------------|----------|\n"

        for col in report_cols.index:
            count = int(null_counts[col])
            pct = null_pcts[col]
            if count == 0:
                continue

            severity = "LOW" if pct < 5 else "MEDIUM" if pct < 20 else "HIGH" if pct < 50 else "CRITICAL"
            result += f"| {col} | {count:,} | {pct:.1f}% | {severity} |\n"

        # Summary
        total_nulls = int(null_counts.sum())
        total_cells = total * len(df.columns)
        result += f"\nTotal: {total_nulls:,} missing values out of {total_cells:,} cells ({total_nulls / total_cells * 100:.2f}%)"

        return result


# =============================================================================
# Tool 2: gwdb_duplicates
# =============================================================================

class GWDBDuplicatesTool(BaseTool):
    """Find duplicate rows."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_duplicates",
            description="Find duplicate rows in a table. Can check exact duplicates (all columns) or duplicates based on specific key columns (e.g., 'id').",
            category="gwdb_analyze",
            tags=["gwdb", "duplicates", "dedup", "quality"],
        ))

    def _execute(
        self,
        table_name: str,
        columns: Optional[str] = None,
        max_show: int = 20,
    ) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        if columns:
            col_list = [c.strip() for c in columns.split(",")]
            missing = [c for c in col_list if c not in df.columns]
            if missing:
                return f"Error: Columns not found: {missing}"
            subset = col_list
            desc = f"by columns: {columns}"
        else:
            subset = None
            desc = "across all columns"

        dupes = df[df.duplicated(subset=subset, keep=False)]
        dupe_count = len(dupes)
        unique_dupes = len(df[df.duplicated(subset=subset, keep="first")])

        result = f"Duplicate Analysis: {table_name} ({desc})\n\n"
        result += f"Total rows: {len(df):,}\n"
        result += f"Duplicate rows: {dupe_count:,} ({dupe_count / len(df) * 100:.1f}%)\n"
        result += f"Unique duplicated groups: {unique_dupes:,}\n"

        if dupe_count == 0:
            result += "\nNo duplicates found!"
            return result

        # Show sample duplicates
        show_cols = list(df.columns[:8])
        sample = dupes.head(max_show)[show_cols].copy()
        for col in sample.select_dtypes(include=["object"]).columns:
            sample[col] = sample[col].astype(str).str[:30]

        result += f"\nSample duplicates (first {min(max_show, dupe_count)}):\n"
        result += sample.to_markdown(index=False)

        return result


# =============================================================================
# Tool 3: gwdb_dtype_check
# =============================================================================

class GWDBDtypeCheckTool(BaseTool):
    """Detect mixed/incorrect data types in columns."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_dtype_check",
            description="Detect columns with mixed or unexpected data types. Finds numeric values stored as strings, dates not parsed, and inconsistent formatting.",
            category="gwdb_analyze",
            tags=["gwdb", "dtype", "types", "quality"],
        ))

    def _execute(self, table_name: str) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        pd = _import_pandas()

        result = f"Data Type Analysis: {table_name}\n\n"
        issues = []

        for col in df.columns:
            col_data = df[col].dropna()
            if len(col_data) == 0:
                continue

            current_dtype = str(df[col].dtype)

            # Check if object column could be numeric
            if df[col].dtype == object:
                numeric_count = 0
                sample = col_data.head(1000)
                for val in sample:
                    try:
                        float(str(val).strip())
                        numeric_count += 1
                    except (ValueError, TypeError):
                        pass

                pct_numeric = numeric_count / len(sample) * 100
                if pct_numeric > 80:
                    issues.append({
                        "column": col,
                        "current_type": current_dtype,
                        "issue": f"Likely numeric ({pct_numeric:.0f}% of values are numbers)",
                        "suggestion": "Convert to float/int",
                    })

                # Check if could be date
                date_patterns = ["-", "/"]
                sample_str = col_data.head(10).astype(str)
                if any(any(p in str(v) for p in date_patterns) for v in sample_str):
                    try:
                        pd.to_datetime(col_data.head(50), format="mixed")
                        issues.append({
                            "column": col,
                            "current_type": current_dtype,
                            "issue": "Likely date/datetime",
                            "suggestion": "Convert to datetime",
                        })
                    except Exception:
                        pass

            # Check numeric columns with suspicious values (all-negative or mostly-negative)
            elif pd.api.types.is_numeric_dtype(df[col]):
                neg_count = (col_data < 0).sum()
                if neg_count > 0 and neg_count > len(col_data) * 0.5:
                    issues.append({
                        "column": col,
                        "current_type": current_dtype,
                        "issue": f"{neg_count} negative values ({neg_count / len(col_data) * 100:.0f}% of data)",
                        "suggestion": "Verify if negative values are expected",
                    })

        if not issues:
            result += "No data type issues detected. All columns look clean."
            return result

        result += f"Found {len(issues)} potential issues:\n\n"
        result += "| Column | Current Type | Issue | Suggestion |\n"
        result += "|--------|-------------|-------|------------|\n"
        for issue in issues:
            result += f"| {issue['column']} | {issue['current_type']} | {issue['issue']} | {issue['suggestion']} |\n"

        return result


# =============================================================================
# Tool 4: gwdb_outliers
# =============================================================================

class GWDBOutliersTool(BaseTool):
    """Detect statistical outliers in numeric columns."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_outliers",
            description="Detect statistical outliers in numeric columns using the IQR method. Reports outlier counts and extreme values for each numeric column.",
            category="gwdb_analyze",
            tags=["gwdb", "outliers", "statistics", "quality"],
        ))

    def _execute(
        self,
        table_name: str,
        columns: Optional[str] = None,
        iqr_multiplier: float = 1.5,
    ) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        pd = _import_pandas()

        if columns:
            col_list = [c.strip() for c in columns.split(",")]
        else:
            col_list = df.select_dtypes(include=["int64", "float64", "int32", "float32"]).columns.tolist()

        if not col_list:
            return "No numeric columns found for outlier detection."

        result = f"Outlier Analysis: {table_name} (IQR x {iqr_multiplier})\n\n"
        result += "| Column | Total | Outliers | % | Min | Q1 | Median | Q3 | Max |\n"
        result += "|--------|-------|----------|---|-----|----|---------|----|-----|\n"

        for col in col_list:
            if col not in df.columns:
                continue
            data = df[col].dropna()
            if len(data) == 0:
                continue

            q1 = data.quantile(0.25)
            q3 = data.quantile(0.75)
            iqr = q3 - q1
            lower = q1 - iqr_multiplier * iqr
            upper = q3 + iqr_multiplier * iqr

            outliers = data[(data < lower) | (data > upper)]
            outlier_count = len(outliers)
            pct = outlier_count / len(data) * 100

            result += (
                f"| {col} | {len(data):,} | {outlier_count:,} | {pct:.1f}% | "
                f"{data.min():.1f} | {q1:.1f} | {data.median():.1f} | {q3:.1f} | {data.max():.1f} |\n"
            )

        return result


# =============================================================================
# Tool 5: gwdb_value_distribution
# =============================================================================

class GWDBValueDistributionTool(BaseTool):
    """Show value frequency distribution for a column."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_value_distribution",
            description="Show the frequency distribution of values in a column. For categorical columns, shows top N value counts. For numeric, shows histogram buckets.",
            category="gwdb_analyze",
            tags=["gwdb", "distribution", "frequency", "histogram"],
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
            return f"Error: Column '{column}' not found."

        pd = _import_pandas()
        col = df[column]

        result = f"Value Distribution: {column}\n"
        result += f"Total: {len(col):,} | Non-null: {col.notna().sum():,} | Unique: {col.nunique():,}\n\n"

        if pd.api.types.is_numeric_dtype(col):
            # Numeric histogram
            data = col.dropna()
            if len(data) == 0:
                return result + "All values are null."

            bins = min(10, col.nunique())
            counts, edges = pd.cut(data, bins=bins, retbins=True)
            freq = counts.value_counts().sort_index()

            result += "| Range | Count | Percentage |\n"
            result += "|-------|-------|------------|\n"
            for interval, count in freq.items():
                pct = count / len(data) * 100
                bar = "#" * int(pct / 2)
                result += f"| {interval} | {count:,} | {pct:.1f}% {bar} |\n"
        else:
            # Categorical value counts
            counts = col.value_counts().head(top_n)
            result += "| Value | Count | Percentage |\n"
            result += "|-------|-------|------------|\n"
            for val, count in counts.items():
                pct = count / len(df) * 100
                bar = "#" * int(pct / 2)
                result += f"| {str(val)[:40]} | {count:,} | {pct:.1f}% {bar} |\n"

            if col.nunique() > top_n:
                result += f"\n... showing top {top_n} of {col.nunique():,} unique values"

        return result


# =============================================================================
# Tool 6: gwdb_data_profile
# =============================================================================

class GWDBDataProfileTool(BaseTool):
    """Full data quality report combining all checks."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_data_profile",
            description="Generate a comprehensive data quality report for a table. Includes: shape, memory, missing values, duplicates, data types, numeric stats, and top issues.",
            category="gwdb_analyze",
            tags=["gwdb", "profile", "quality", "report", "comprehensive"],
        ))

    def _execute(self, table_name: str) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        pd = _import_pandas()
        total = len(df)

        result = f"# Data Profile: {table_name}\n\n"

        # 1. Shape & Memory
        mem_mb = df.memory_usage(deep=True).sum() / 1024 / 1024
        result += f"## Overview\n"
        result += f"- Rows: {total:,}\n"
        result += f"- Columns: {len(df.columns)}\n"
        result += f"- Memory: {mem_mb:.1f} MB\n\n"

        # 2. Column Types
        type_counts = df.dtypes.value_counts()
        result += "## Column Types\n"
        for dtype, count in type_counts.items():
            result += f"- {dtype}: {count} columns\n"
        result += "\n"

        # 3. Missing Values Summary
        null_cols = df.isnull().sum()
        null_cols = null_cols[null_cols > 0].sort_values(ascending=False)
        result += f"## Missing Values\n"
        if null_cols.empty:
            result += "- No missing values!\n\n"
        else:
            result += f"- {len(null_cols)} columns have nulls\n"
            for col in null_cols.head(10).index:
                pct = null_cols[col] / total * 100
                result += f"  - {col}: {null_cols[col]:,} ({pct:.1f}%)\n"
            if len(null_cols) > 10:
                result += f"  - ... and {len(null_cols) - 10} more\n"
            result += "\n"

        # 4. Duplicates
        exact_dupes = df.duplicated().sum()
        result += f"## Duplicates\n"
        result += f"- Exact duplicate rows: {exact_dupes:,} ({exact_dupes / total * 100:.1f}%)\n\n"

        # 5. Numeric Column Stats
        numeric_cols = df.select_dtypes(include=["int64", "float64", "int32", "float32"]).columns
        if len(numeric_cols) > 0:
            result += "## Numeric Columns Summary\n"
            result += "| Column | Min | Mean | Median | Max | Std |\n"
            result += "|--------|-----|------|--------|-----|-----|\n"
            for col in numeric_cols[:10]:
                data = df[col].dropna()
                if len(data) > 0:
                    result += f"| {col} | {data.min():.1f} | {data.mean():.1f} | {data.median():.1f} | {data.max():.1f} | {data.std():.1f} |\n"
            result += "\n"

        # 6. Categorical Column Stats
        text_cols = df.select_dtypes(include=["object"]).columns
        if len(text_cols) > 0:
            result += "## Text Columns Summary\n"
            result += "| Column | Unique | Top Value | Top Count |\n"
            result += "|--------|--------|-----------|----------|\n"
            for col in text_cols[:10]:
                unique = df[col].nunique()
                top_val = df[col].value_counts().index[0] if df[col].notna().any() else "N/A"
                top_count = df[col].value_counts().iloc[0] if df[col].notna().any() else 0
                result += f"| {col} | {unique:,} | {str(top_val)[:25]} | {top_count:,} |\n"
            result += "\n"

        # 7. Quality Score
        total_cells = total * len(df.columns)
        total_nulls = df.isnull().sum().sum()
        completeness = (1 - total_nulls / total_cells) * 100
        uniqueness = (1 - exact_dupes / total) * 100

        result += "## Quality Score\n"
        result += f"- Completeness: {completeness:.1f}%\n"
        result += f"- Uniqueness: {uniqueness:.1f}%\n"
        result += f"- Overall: {(completeness + uniqueness) / 2:.1f}%\n"

        return result


# =============================================================================
# Tool 7: gwdb_compare_schemas
# =============================================================================

class GWDBCompareSchemasTool(BaseTool):
    """Compare columns between two loaded tables."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_compare_schemas",
            description=(
                "Compare the columns of two loaded tables. Shows shared columns, "
                "columns unique to each table, and type mismatches on shared columns. "
                "Useful for schema alignment before merging or pushing data."
            ),
            category="gwdb_analyze",
            tags=["gwdb", "schema", "compare", "mapping", "validation"],
        ))

    def _execute(self, table_a: str, table_b: Optional[str] = None) -> str:
        df_a, err = _get_df_or_error(table_a)
        if err:
            return err

        # If no second table, compare against all other loaded tables
        if not table_b:
            all_tables = list_dataframes()
            other_tables = [t for t in all_tables if t != table_a]
            if not other_tables:
                return f"Only one table loaded ('{table_a}'). Load a second table to compare."

            result = f"# Schema Comparison: {table_a} vs all loaded tables\n\n"
            result += f"Source: {table_a} ({len(df_a.columns)} columns)\n\n"

            for other_name in other_tables:
                df_b = get_dataframe(other_name)
                cols_a = set(df_a.columns)
                cols_b = set(df_b.columns)
                shared = cols_a & cols_b
                only_a = cols_a - cols_b
                only_b = cols_b - cols_a

                result += f"## vs {other_name} ({len(df_b.columns)} columns)\n"
                result += f"- Shared columns: {len(shared)}\n"
                result += f"- Only in {table_a}: {len(only_a)}\n"
                result += f"- Only in {other_name}: {len(only_b)}\n"
                if shared:
                    result += f"- Shared: {', '.join(sorted(shared))}\n"
                result += "\n"

            return result

        df_b, err = _get_df_or_error(table_b)
        if err:
            return err

        cols_a = set(df_a.columns)
        cols_b = set(df_b.columns)
        shared = sorted(cols_a & cols_b)
        only_a = sorted(cols_a - cols_b)
        only_b = sorted(cols_b - cols_a)

        pd = _import_pandas()

        result = f"# Schema Comparison: {table_a} vs {table_b}\n\n"

        # Shared columns with type comparison
        if shared:
            result += f"## Shared Columns ({len(shared)})\n"
            result += "| Column | Type in {a} | Type in {b} | Match |\n".format(a=table_a, b=table_b)
            result += "|--------|------------|------------|-------|\n"
            for col in shared:
                type_a = str(df_a[col].dtype)
                type_b = str(df_b[col].dtype)
                match = "OK" if type_a == type_b else "MISMATCH"
                result += f"| {col} | {type_a} | {type_b} | {match} |\n"
            result += "\n"

        if only_a:
            result += f"## Only in {table_a} ({len(only_a)})\n"
            for col in only_a:
                result += f"- {col} ({df_a[col].dtype})\n"
            result += "\n"

        if only_b:
            result += f"## Only in {table_b} ({len(only_b)})\n"
            for col in only_b:
                result += f"- {col} ({df_b[col].dtype})\n"
            result += "\n"

        result += f"## Summary\n"
        result += f"- {table_a}: {len(cols_a)} columns\n"
        result += f"- {table_b}: {len(cols_b)} columns\n"
        result += f"- Shared: {len(shared)}\n"
        result += f"- Unique to {table_a}: {len(only_a)}\n"
        result += f"- Unique to {table_b}: {len(only_b)}\n"

        return result
