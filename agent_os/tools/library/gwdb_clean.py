"""Data Cleaning Tools - Remove duplicates, fill missing values, drop columns.

Generic cleaning tools that work with any loaded data.
"""

from typing import Any, Dict, List, Optional

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.logging import get_logger
from agent_os.tools.library.gwdb_ingest import (
    get_dataframe, store_dataframe, list_dataframes, _import_pandas
)

logger = get_logger(__name__)


def _get_df_or_error(table_name: str):
    df = get_dataframe(table_name)
    if df is None:
        available = ", ".join(list_dataframes().keys()) or "none"
        return None, f"Error: Table '{table_name}' not loaded. Available: {available}"
    return df, None


# =============================================================================
# Tool 1: gwdb_remove_duplicates
# =============================================================================

class GWDBRemoveDuplicatesTool(BaseTool):
    """Remove duplicate rows from a loaded table."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_remove_duplicates",
            description=(
                "Remove duplicate rows from a table (in-memory). "
                "By default removes exact duplicates keeping the first occurrence. "
                "Optionally specify subset columns to check for duplicates. "
                "Example: subset='id' keeps first row per unique ID."
            ),
            category="gwdb_clean",
            tags=["gwdb", "clean", "duplicates", "dedup"],
        ))

    def _execute(
        self,
        table_name: str,
        subset: Optional[str] = None,
        keep: str = "first",
    ) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        original_count = len(df)

        # Parse subset columns
        subset_cols = None
        if subset:
            subset_cols = [c.strip() for c in subset.split(",")]
            missing = [c for c in subset_cols if c not in df.columns]
            if missing:
                return f"Error: Columns not found: {missing}. Available: {', '.join(df.columns[:20])}"

        # Remove duplicates
        if keep not in ("first", "last", False):
            keep = "first"

        cleaned = df.drop_duplicates(subset=subset_cols, keep=keep)
        removed = original_count - len(cleaned)

        # Update the stored DataFrame
        store_dataframe(table_name, cleaned)

        result = f"# Duplicate Removal: {table_name}\n\n"
        result += f"- Original rows: {original_count:,}\n"
        result += f"- Duplicates removed: {removed:,}\n"
        result += f"- Remaining rows: {len(cleaned):,}\n"
        if subset_cols:
            result += f"- Checked columns: {', '.join(subset_cols)}\n"
        else:
            result += "- Checked: all columns (exact duplicates)\n"
        result += f"- Keep: {keep}\n"

        return result


# =============================================================================
# Tool 2: gwdb_fill_missing
# =============================================================================

class GWDBFillMissingTool(BaseTool):
    """Fill missing/null values in specific columns."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_fill_missing",
            description=(
                "Fill missing (null/NaN) values in a table. "
                "strategy options: "
                "'median' (numeric only), 'mean' (numeric only), 'mode' (most common value), "
                "'zero' (fill with 0), 'unknown' (fill text columns with 'Unknown'), "
                "'forward' (forward fill), 'value:X' (fill with custom value X). "
                "columns: optional comma-separated column names to fill (default: all columns). "
                "Example: strategy='median', columns='price,quantity'"
            ),
            category="gwdb_clean",
            tags=["gwdb", "clean", "missing", "fill", "impute"],
        ))

    def _execute(
        self,
        table_name: str,
        strategy: str = "unknown",
        columns: Optional[str] = None,
    ) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        pd = _import_pandas()

        # Parse target columns
        if columns:
            target_cols = [c.strip() for c in columns.split(",")]
            missing = [c for c in target_cols if c not in df.columns]
            if missing:
                return f"Error: Columns not found: {missing}"
        else:
            target_cols = list(df.columns)

        # Track what was filled
        fill_report = []
        cleaned = df.copy()

        for col in target_cols:
            null_count = cleaned[col].isnull().sum()
            if null_count == 0:
                continue

            is_numeric = pd.api.types.is_numeric_dtype(cleaned[col])

            if strategy == "median":
                if is_numeric:
                    val = cleaned[col].median()
                    cleaned[col] = cleaned[col].fillna(val)
                    fill_report.append(f"  {col}: {null_count:,} nulls -> median ({val:.2f})")
                else:
                    cleaned[col] = cleaned[col].fillna("Unknown")
                    fill_report.append(f"  {col}: {null_count:,} nulls -> 'Unknown' (text column)")
            elif strategy == "mean":
                if is_numeric:
                    val = cleaned[col].mean()
                    cleaned[col] = cleaned[col].fillna(val)
                    fill_report.append(f"  {col}: {null_count:,} nulls -> mean ({val:.2f})")
                else:
                    cleaned[col] = cleaned[col].fillna("Unknown")
                    fill_report.append(f"  {col}: {null_count:,} nulls -> 'Unknown' (text column)")
            elif strategy == "mode":
                mode_val = cleaned[col].mode()
                if len(mode_val) > 0:
                    cleaned[col] = cleaned[col].fillna(mode_val.iloc[0])
                    fill_report.append(f"  {col}: {null_count:,} nulls -> mode ({mode_val.iloc[0]})")
            elif strategy == "zero":
                cleaned[col] = cleaned[col].fillna(0)
                fill_report.append(f"  {col}: {null_count:,} nulls -> 0")
            elif strategy == "unknown":
                if is_numeric:
                    cleaned[col] = cleaned[col].fillna(0)
                    fill_report.append(f"  {col}: {null_count:,} nulls -> 0 (numeric)")
                else:
                    cleaned[col] = cleaned[col].fillna("Unknown")
                    fill_report.append(f"  {col}: {null_count:,} nulls -> 'Unknown'")
            elif strategy == "forward":
                cleaned[col] = cleaned[col].ffill()
                fill_report.append(f"  {col}: {null_count:,} nulls -> forward filled")
            elif strategy.startswith("value:"):
                custom_val = strategy.split(":", 1)[1]
                if is_numeric:
                    try:
                        custom_val = float(custom_val)
                    except ValueError:
                        pass
                cleaned[col] = cleaned[col].fillna(custom_val)
                fill_report.append(f"  {col}: {null_count:,} nulls -> '{custom_val}'")
            else:
                return f"Error: Unknown strategy '{strategy}'. Use: median, mean, mode, zero, unknown, forward, value:X"

        # Update stored DataFrame
        store_dataframe(table_name, cleaned)

        # Remaining nulls
        remaining_nulls = cleaned[target_cols].isnull().sum().sum()

        result = f"# Fill Missing Values: {table_name}\n\n"
        result += f"Strategy: {strategy}\n\n"
        if fill_report:
            result += "Columns filled:\n"
            result += "\n".join(fill_report) + "\n\n"
        else:
            result += "No missing values found in target columns.\n\n"
        result += f"Remaining nulls: {remaining_nulls:,}\n"

        return result


# =============================================================================
# Tool 3: gwdb_drop_columns
# =============================================================================

class GWDBDropColumnsTool(BaseTool):
    """Drop columns from a loaded table."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_drop_columns",
            description=(
                "Drop (remove) columns from a table. "
                "columns: comma-separated column names to drop. "
                "Example: columns='Remarks,OldField,TempColumn'"
            ),
            category="gwdb_clean",
            tags=["gwdb", "clean", "drop", "columns", "remove"],
        ))

    def _execute(self, table_name: str, columns: str) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        cols_to_drop = [c.strip() for c in columns.split(",")]
        missing = [c for c in cols_to_drop if c not in df.columns]
        if missing:
            return f"Error: Columns not found: {missing}. Available: {', '.join(df.columns[:20])}"

        cleaned = df.drop(columns=cols_to_drop)
        store_dataframe(table_name, cleaned)

        return (
            f"Dropped {len(cols_to_drop)} columns from {table_name}: {', '.join(cols_to_drop)}\n"
            f"Remaining columns: {len(cleaned.columns)}"
        )


# =============================================================================
# Tool 4: gwdb_rename_columns
# =============================================================================

class GWDBRenameColumnsTool(BaseTool):
    """Rename columns in a loaded table."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_rename_columns",
            description=(
                "Rename columns in a table. "
                "mapping: comma-separated old=new pairs. "
                "Example: mapping='OldName=NewName,County=CountyName'"
            ),
            category="gwdb_clean",
            tags=["gwdb", "clean", "rename", "columns"],
        ))

    def _execute(self, table_name: str, mapping: str) -> str:
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        rename_map = {}
        for pair in mapping.split(","):
            pair = pair.strip()
            if "=" not in pair:
                return f"Error: Invalid mapping '{pair}'. Use format: old=new"
            old, new = pair.split("=", 1)
            old, new = old.strip(), new.strip()
            if old not in df.columns:
                return f"Error: Column '{old}' not found"
            rename_map[old] = new

        cleaned = df.rename(columns=rename_map)
        store_dataframe(table_name, cleaned)

        result = f"Renamed {len(rename_map)} columns in {table_name}:\n"
        for old, new in rename_map.items():
            result += f"  {old} -> {new}\n"
        return result
