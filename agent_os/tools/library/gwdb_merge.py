"""Data Merge Tools - Union tables and align schemas for combining datasets.

Combine multiple loaded tables by stacking rows and aligning column schemas.
All operations are dynamic - no hardcoded column names or table structures.
"""

from typing import Optional

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.logging import get_logger
from agent_os.tools.library.gwdb_ingest import (
    get_dataframe, store_dataframe, list_dataframes, _import_pandas
)

logger = get_logger(__name__)


def _get_df_or_error(table_name: str):
    """Get a DataFrame or return an error string."""
    df = get_dataframe(table_name)
    if df is None:
        available = ", ".join(list_dataframes().keys()) or "none"
        return None, f"Error: Table '{table_name}' not loaded. Available: {available}"
    return df, None


# =============================================================================
# Tool 1: gwdb_align_columns
# =============================================================================

class GWDBAlignColumnsTool(BaseTool):
    """Align a table's schema to a target column set for union compatibility."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_align_columns",
            description=(
                "Prepare a table for union by aligning its schema to a target column set. "
                "Can rename columns, add missing columns as NULL, drop extra columns, "
                "and reorder to match target order. Modifies the table in-place. "
                "column_mapping: 'old1=new1,old2=new2' to rename before alignment. "
                "target_columns: comma-separated target column names in desired order. "
                "Example: table_name='sales_q3', target_columns='id,product,amount,date,region', "
                "column_mapping='product_name=product,sale_date=date'"
            ),
            category="gwdb_merge",
            tags=["gwdb", "merge", "align", "schema", "rename", "prepare"],
        ))

    def _execute(
        self,
        table_name: str,
        target_columns: str,
        column_mapping: Optional[str] = None,
        drop_extra: bool = True,
        fill_missing: bool = True,
    ) -> str:
        pd = _import_pandas()
        df, err = _get_df_or_error(table_name)
        if err:
            return err

        original_columns = list(df.columns)

        # Parse target columns
        targets = [c.strip() for c in target_columns.split(",") if c.strip()]
        if not targets:
            return "Error: target_columns is required. Provide comma-separated column names."

        # Step 1: Apply column_mapping (rename) first
        renamed = {}
        if column_mapping:
            for pair in column_mapping.split(","):
                pair = pair.strip()
                if "=" not in pair:
                    return f"Error: Invalid mapping '{pair}'. Use format: old=new"
                old, new = pair.split("=", 1)
                old, new = old.strip(), new.strip()
                if old not in df.columns:
                    return f"Error: Column '{old}' not found in {table_name}. Available: {', '.join(df.columns)}"
                renamed[old] = new

            df = df.rename(columns=renamed)

        # Step 2: Determine what to add, drop, and keep
        current_cols = set(df.columns)
        target_set = set(targets)

        columns_to_add = [c for c in targets if c not in current_cols]
        columns_to_drop = [c for c in df.columns if c not in target_set]

        # Step 3: Add missing columns as NULL
        added = []
        if fill_missing:
            for col in columns_to_add:
                df[col] = pd.NA
                added.append(col)

        # Step 4: Drop extra columns
        dropped = []
        if drop_extra:
            drop_list = [c for c in columns_to_drop if c in df.columns]
            if drop_list:
                df = df.drop(columns=drop_list)
                dropped = drop_list

        # Step 5: Reorder columns to match target order
        final_order = [c for c in targets if c in df.columns]
        remaining = [c for c in df.columns if c not in target_set]
        if not drop_extra:
            final_order.extend(remaining)

        df = df[final_order]

        # Step 6: Store modified table in-place
        store_dataframe(table_name, df)

        # Build output report
        output = f"# Column Alignment: {table_name}\n\n"
        output += f"Target columns: {', '.join(targets)}\n\n"

        if renamed:
            output += "## Renamed Columns\n"
            for old, new in renamed.items():
                output += f"  {old} -> {new}\n"
            output += "\n"

        if added:
            output += f"## Added Columns (filled with NULL) ({len(added)})\n"
            for col in added:
                output += f"  + {col}\n"
            output += "\n"

        if dropped:
            output += f"## Dropped Columns ({len(dropped)})\n"
            for col in dropped:
                output += f"  - {col}\n"
            output += "\n"

        output += "## Final Schema\n"
        output += f"Columns ({len(df.columns)}): {', '.join(df.columns)}\n"
        output += f"Rows: {len(df):,}\n\n"

        # Schema detail table
        output += "| Column | Type | Non-Null | Source |\n"
        output += "|--------|------|----------|--------|\n"
        for col in df.columns:
            dtype = str(df[col].dtype)
            non_null = df[col].notna().sum()
            if col in added:
                source = "ADDED (NULL)"
            elif col in renamed.values():
                orig = [k for k, v in renamed.items() if v == col]
                source = f"RENAMED from {orig[0]}" if orig else "original"
            else:
                source = "original"
            output += f"| {col} | {dtype} | {non_null:,} | {source} |\n"

        return output


# =============================================================================
# Tool 2: gwdb_union_tables
# =============================================================================

class GWDBUnionTablesTool(BaseTool):
    """Combine multiple loaded tables into one by stacking rows (UNION ALL)."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_union_tables",
            description=(
                "Combine multiple loaded tables into one by stacking rows (UNION ALL). "
                "Supports 'inner' mode (only shared columns) or 'outer' mode (all columns, "
                "NULL for missing). Optionally dedup and sort the result. "
                "Adds a '_source_table' column to track which table each row came from. "
                "Example: table_names='sales_q1,sales_q2,sales_q3', result_name='sales_all', "
                "mode='outer', dedup=True, sort_by='date'"
            ),
            category="gwdb_merge",
            tags=["gwdb", "merge", "union", "combine", "stack", "concat"],
        ))

    def _execute(
        self,
        table_names: str,
        result_name: str,
        mode: str = "outer",
        dedup: bool = False,
        sort_by: Optional[str] = None,
    ) -> str:
        pd = _import_pandas()

        # Step 1: Parse and validate table names
        names = [n.strip() for n in table_names.split(",") if n.strip()]

        if len(names) < 2:
            return "Error: At least 2 table names required. Provide comma-separated names."

        # Validate all tables exist BEFORE starting
        missing = []
        dfs = {}
        for name in names:
            df = get_dataframe(name)
            if df is None:
                missing.append(name)
            else:
                dfs[name] = df

        if missing:
            available = ", ".join(list_dataframes().keys()) or "none"
            return f"Error: Tables not found: {', '.join(missing)}. Available: {available}"

        # Step 2: Validate mode
        if mode not in ("inner", "outer"):
            return "Error: mode must be 'inner' or 'outer'. inner=shared columns only, outer=all columns with NULLs."

        # Step 3: Build schema alignment report
        col_sets = {name: set(df.columns) for name, df in dfs.items()}
        all_columns = set()
        for cols in col_sets.values():
            all_columns |= cols

        shared_columns = set.intersection(*col_sets.values())

        # Type mismatch detection on shared columns
        type_mismatches = []
        for col in sorted(shared_columns):
            types_seen = {}
            for name, df in dfs.items():
                types_seen[name] = str(df[col].dtype)
            unique_types = set(types_seen.values())
            if len(unique_types) > 1:
                type_mismatches.append((col, types_seen))

        report = "## Schema Alignment Report\n\n"
        report += f"Tables: {len(names)}\n"
        report += f"Shared columns: {len(shared_columns)}\n"
        report += f"Total unique columns: {len(all_columns)}\n\n"

        if shared_columns:
            report += f"### Shared Columns ({len(shared_columns)})\n"
            report += f"{', '.join(sorted(shared_columns))}\n\n"

        # Columns unique to each table
        has_unique = False
        for name in names:
            unique = col_sets[name] - shared_columns
            if unique:
                has_unique = True
                report += f"### Only in {name} ({len(unique)})\n"
                report += f"{', '.join(sorted(unique))}\n\n"

        if type_mismatches:
            report += "### Type Mismatches on Shared Columns\n"
            report += "| Column | " + " | ".join(names) + " |\n"
            report += "|--------" + "|--------" * len(names) + "|\n"
            for col, types_seen in type_mismatches:
                row = f"| {col} | " + " | ".join(types_seen[n] for n in names) + " |"
                report += row + "\n"
            report += "\n"

        if not has_unique and not type_mismatches:
            report += "All tables have matching schemas.\n\n"

        # Step 4: Perform the concatenation
        join = "inner" if mode == "inner" else "outer"

        frames = []
        row_counts = {}
        for name in names:
            df_copy = dfs[name].copy()
            df_copy["_source_table"] = name
            frames.append(df_copy)
            row_counts[name] = len(dfs[name])

        combined = pd.concat(frames, join=join, ignore_index=True)

        # Step 5: Optional dedup
        rows_before_dedup = len(combined)
        dupes_removed = 0
        if dedup:
            dedup_cols = [c for c in combined.columns if c != "_source_table"]
            combined = combined.drop_duplicates(subset=dedup_cols, ignore_index=True)
            dupes_removed = rows_before_dedup - len(combined)

        # Step 6: Optional sort
        if sort_by:
            if sort_by not in combined.columns:
                available_cols = ", ".join(c for c in combined.columns if c != "_source_table")
                return f"Error: sort_by column '{sort_by}' not in result columns: {available_cols}"
            combined = combined.sort_values(sort_by, ignore_index=True)

        # Step 7: Store and return summary
        store_dataframe(result_name, combined)

        output = f"# Union Result: {result_name}\n\n"
        output += report

        output += "## Row Counts per Source\n\n"
        output += "| Table | Rows |\n"
        output += "|-------|------|\n"
        for name in names:
            output += f"| {name} | {row_counts[name]:,} |\n"
        output += f"| **Total (raw)** | **{rows_before_dedup:,}** |\n"

        if dedup:
            output += f"\nDuplicates removed: {dupes_removed:,}\n"

        data_cols = [c for c in combined.columns if c != "_source_table"]
        output += f"\n## Combined Table: {result_name}\n"
        output += f"- Rows: {len(combined):,}\n"
        output += f"- Data columns: {len(data_cols)}\n"
        output += f"- Mode: {mode}\n"
        output += f"- Columns: {', '.join(data_cols)}\n"
        output += f"- Tracking column: _source_table\n\n"

        # Sample data (first 5 rows)
        sample = combined.head(5).copy()
        for col in sample.select_dtypes(include=["object"]).columns:
            sample[col] = sample[col].astype(str).str[:30]
        output += "## Sample (first 5 rows)\n\n"
        try:
            output += sample.to_markdown(index=False)
        except Exception:
            # Fallback if tabulate not installed
            output += str(sample.to_string(index=False))
        output += "\n"

        return output
