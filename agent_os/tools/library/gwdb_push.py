"""Data Push Tools - Push loaded data to SQLite with HITL enforcement.

All push operations are dynamic. The user controls what tables and columns
to push. No hardcoded schema mappings or table definitions.
"""

import hashlib
import hmac
import json
import os
import sqlite3
import time
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.logging import get_logger
from agent_os.tools.library.gwdb_ingest import get_dataframe, list_dataframes, _import_pandas

logger = get_logger(__name__)

# =============================================================================
# HITL Approval Token System
# =============================================================================

_approval_lock = threading.Lock()
_approval_tokens: Dict[str, Dict[str, Any]] = {}  # token -> {plan, timestamp, used}
_push_status: Dict[str, Dict[str, Any]] = {}  # push_id -> {status, tables, progress}

APPROVAL_SECRET = os.getenv("PUSH_APPROVAL_SECRET", "agent-os-hitl-approval-key")
APPROVAL_EXPIRY_SECONDS = int(os.getenv("PUSH_APPROVAL_EXPIRY", "300"))


def _generate_approval_token(plan: Dict) -> str:
    """Generate HMAC-signed approval token."""
    timestamp = str(int(time.time()))
    plan_hash = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()[:16]
    signature = hmac.new(
        APPROVAL_SECRET.encode(),
        f"{plan_hash}:{timestamp}".encode(),
        hashlib.sha256
    ).hexdigest()[:16]

    token = f"push-{plan_hash}-{timestamp}-{signature}"

    with _approval_lock:
        _approval_tokens[token] = {
            "plan": plan,
            "timestamp": float(timestamp),
            "used": False,
        }

    return token


def _validate_approval_token(token: str) -> tuple:
    """Validate token. Returns (valid, plan_or_error)."""
    with _approval_lock:
        if token not in _approval_tokens:
            return False, "Invalid approval token. Run gwdb_request_approval first."

        record = _approval_tokens[token]

        if record["used"]:
            return False, "Token already used. Request new approval."

        elapsed = time.time() - record["timestamp"]
        if elapsed > APPROVAL_EXPIRY_SECONDS:
            return False, f"Token expired ({int(elapsed)}s > {APPROVAL_EXPIRY_SECONDS}s). Request new approval."

        # Mark as used
        record["used"] = True
        return True, record["plan"]


# =============================================================================
# Tool 1: gwdb_map_to_tables - Show what will be pushed
# =============================================================================

class GWDBMapToTablesTool(BaseTool):
    """Show what loaded data will be pushed to SQL."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_map_to_tables",
            description=(
                "Show the structure of a loaded table that will be pushed to SQL. "
                "Displays column names, types, sample values, and row count. "
                "This is informational only -- no data is modified."
            ),
            category="gwdb_push",
            tags=["gwdb", "push", "mapping", "schema"],
        ))

    def _execute(self, source_table: str) -> str:
        df = get_dataframe(source_table)
        if df is None:
            available = ", ".join(list_dataframes().keys()) or "none"
            return f"Error: Table '{source_table}' not loaded. Available: {available}"

        result = f"# Push Mapping: {source_table}\n\n"
        result += f"Rows: {len(df):,} | Columns: {len(df.columns)}\n\n"

        result += "| Column | Type | Non-Null | Sample |\n"
        result += "|--------|------|----------|--------|\n"
        for col in df.columns:
            dtype = str(df[col].dtype)
            non_null = df[col].notna().sum()
            sample = str(df[col].dropna().iloc[0])[:30] if df[col].notna().any() else "N/A"
            result += f"| {col} | {dtype} | {non_null:,} | {sample} |\n"

        result += f"\nThis table will be pushed as a single SQL table named '{source_table}'.\n"
        result += "To proceed, call gwdb_preview_push."

        return result


# =============================================================================
# Tool 2: gwdb_preview_push - Dry run
# =============================================================================

class GWDBPreviewPushTool(BaseTool):
    """Dry-run: show what will be inserted."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_preview_push",
            description=(
                "DRY RUN -- show exactly what data will be pushed to SQL, "
                "with row counts and sample rows. No data is modified. "
                "Always call this before gwdb_request_approval."
            ),
            category="gwdb_push",
            tags=["gwdb", "push", "preview", "dry-run"],
        ))

    def _execute(
        self,
        source_table: str,
        target_table_name: Optional[str] = None,
        columns: Optional[str] = None,
        conditions: Optional[str] = None,
        sample_rows: int = 5,
    ) -> str:
        df = get_dataframe(source_table)
        if df is None:
            available = ", ".join(list_dataframes().keys()) or "none"
            return f"Error: Table '{source_table}' not loaded. Available: {available}"

        pd = _import_pandas()
        target_name = target_table_name or source_table

        # Apply optional filter
        if conditions:
            try:
                df = df.query(conditions)
            except Exception as e:
                return f"Error in conditions: {e}"

        # Select specific columns if requested
        if columns:
            col_list = [c.strip() for c in columns.split(",")]
            missing = [c for c in col_list if c not in df.columns]
            if missing:
                return f"Error: Columns not found: {missing}"
            df = df[col_list]

        non_null_rows = df.dropna(how="all").shape[0]

        result = f"# Push Preview (DRY RUN)\n\n"
        result += f"Source: {source_table} ({len(df):,} rows, {len(df.columns)} columns)\n"
        result += f"Target SQL table: {target_name}\n"
        result += f"Non-null rows: {non_null_rows:,}\n\n"

        # Sample data
        sample = df.head(sample_rows).copy()
        for col in sample.select_dtypes(include=["object"]).columns:
            sample[col] = sample[col].astype(str).str[:30]
        result += "## Sample Data\n"
        result += sample.to_markdown(index=False)

        result += "\n\n---\n"
        result += "**This is a DRY RUN. No data has been modified.**\n"
        result += "To proceed, call gwdb_request_approval."

        return result


# =============================================================================
# Tool 3: gwdb_request_approval (HITL CHECKPOINT)
# =============================================================================

class GWDBRequestApprovalTool(BaseTool):
    """HITL checkpoint -- request user approval before pushing data."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_request_approval",
            description=(
                "HUMAN-IN-THE-LOOP CHECKPOINT. Generates an approval token for pushing data. "
                "The user MUST explicitly approve before any data is written. "
                "Returns an approval_token that must be passed to gwdb_execute_push. "
                "Token expires in 5 minutes. "
                "IMPORTANT: Always pass output_dir from context so the database file appears in the UI."
            ),
            category="gwdb_push",
            tags=["gwdb", "push", "hitl", "approval"],
        ))

    def _execute(
        self,
        source_table: str,
        target_db_path: str = "output.db",
        target_table_name: Optional[str] = None,
        columns: Optional[str] = None,
        conditions: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> str:
        df = get_dataframe(source_table)
        if df is None:
            available = ", ".join(list_dataframes().keys()) or "none"
            return f"Error: Table '{source_table}' not loaded. Available: {available}"

        target_name = target_table_name or source_table

        # Resolve output path: if output_dir provided, save there so UI can find it
        if output_dir:
            resolved_db_path = str(Path(output_dir) / Path(target_db_path).name)
        else:
            resolved_db_path = target_db_path

        # Build plan
        plan = {
            "source_table": source_table,
            "source_rows": len(df),
            "target_db": resolved_db_path,
            "target_table": target_name,
            "columns": columns,
            "conditions": conditions,
            "timestamp": time.time(),
        }

        token = _generate_approval_token(plan)

        result = "# APPROVAL REQUIRED\n\n"
        result += f"Ready to push data to SQLite database.\n\n"
        result += f"| Detail | Value |\n"
        result += f"|--------|-------|\n"
        result += f"| Source table | {source_table} |\n"
        result += f"| Source rows | {len(df):,} |\n"
        result += f"| Target database | {resolved_db_path} |\n"
        result += f"| Target SQL table | {target_name} |\n"
        if columns:
            result += f"| Columns | {columns} |\n"
        if conditions:
            result += f"| Filter | {conditions} |\n"

        result += f"\n**Approval Token:** `{token}`\n"
        result += f"**Expires in:** {APPROVAL_EXPIRY_SECONDS // 60} minutes\n\n"
        result += "**Do you approve this push? Please confirm with the user.**"

        return result


# =============================================================================
# Tool 4: gwdb_execute_push (REQUIRES APPROVAL TOKEN)
# =============================================================================

class GWDBExecutePushTool(BaseTool):
    """Execute push -- REQUIRES valid approval token."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_execute_push",
            description=(
                "Push data from a loaded table to a SQLite database. "
                "REQUIRES a valid approval_token from gwdb_request_approval. "
                "Will FAIL without a token -- this is a safety mechanism."
            ),
            category="gwdb_push",
            tags=["gwdb", "push", "execute", "write"],
        ))

    def _execute(
        self,
        approval_token: str,
        target_db_path: Optional[str] = None,
    ) -> str:
        # Validate token
        valid, plan_or_error = _validate_approval_token(approval_token)
        if not valid:
            return f"PUSH BLOCKED: {plan_or_error}"

        plan = plan_or_error
        source_table = plan["source_table"]
        df = get_dataframe(source_table)
        if df is None:
            return f"Error: Source table '{source_table}' no longer loaded."

        pd = _import_pandas()
        push_id = f"push-{int(time.time())}"
        db_path = Path(target_db_path or plan["target_db"])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        target_name = plan.get("target_table", source_table)

        # Apply optional filter from plan
        conditions = plan.get("conditions")
        if conditions:
            try:
                df = df.query(conditions)
            except Exception as e:
                return f"Error applying filter: {e}"

        # Select columns from plan
        columns_str = plan.get("columns")
        if columns_str:
            col_list = [c.strip() for c in columns_str.split(",")]
            df = df[[c for c in col_list if c in df.columns]]

        # Drop all-null rows
        df = df.dropna(how="all")

        try:
            conn = sqlite3.connect(str(db_path))
            df.to_sql(target_name, conn, if_exists="replace", index=False)
            conn.commit()

            # Verify
            cursor = conn.execute(f"SELECT COUNT(*) FROM [{target_name}]")
            verified_count = cursor.fetchone()[0]
            conn.close()

            match = "OK" if len(df) == verified_count else "MISMATCH"

            # Store push status
            with _approval_lock:
                _push_status[push_id] = {
                    "status": "completed",
                    "source": source_table,
                    "target_table": target_name,
                    "rows_pushed": len(df),
                    "rows_verified": verified_count,
                    "db_path": str(db_path),
                    "timestamp": time.time(),
                }

            size_mb = db_path.stat().st_size / 1024 / 1024 if db_path.exists() else 0

            result = f"# Push Complete: {push_id}\n\n"
            result += f"| Detail | Value |\n"
            result += f"|--------|-------|\n"
            result += f"| Database | {db_path} |\n"
            result += f"| Table | {target_name} |\n"
            result += f"| Rows pushed | {len(df):,} |\n"
            result += f"| Rows verified | {verified_count:,} |\n"
            result += f"| Status | {match} |\n"
            result += f"| Database size | {size_mb:.1f} MB |\n"

            return result

        except Exception as e:
            with _approval_lock:
                _push_status[push_id] = {
                    "status": "failed",
                    "error": str(e),
                    "db_path": str(db_path),
                    "timestamp": time.time(),
                }
            return f"Push failed: {e}"


# =============================================================================
# Tool 5: gwdb_verify_push
# =============================================================================

class GWDBVerifyPushTool(BaseTool):
    """Verify pushed data by querying target database."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_verify_push",
            description=(
                "After a push, verify the target SQLite database by showing "
                "all tables, row counts, and sample data."
            ),
            category="gwdb_push",
            tags=["gwdb", "push", "verify", "check"],
        ))

    def _execute(self, db_path: str, sample_rows: int = 3) -> str:
        pd = _import_pandas()
        path = Path(db_path)

        if not path.exists():
            return f"Error: Database not found: {db_path}"

        try:
            conn = sqlite3.connect(str(path))

            # Get all tables
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = [row[0] for row in cursor.fetchall()]

            if not tables:
                conn.close()
                return "Database is empty -- no tables found."

            result = f"# Verification: {db_path}\n\n"
            result += f"Tables: {len(tables)}\n\n"

            for table in tables:
                cursor = conn.execute(f"SELECT COUNT(*) FROM [{table}]")
                count = cursor.fetchone()[0]

                # Get column info
                cursor = conn.execute(f"PRAGMA table_info([{table}])")
                columns = [row[1] for row in cursor.fetchall()]

                result += f"## {table}\n"
                result += f"Rows: {count:,} | Columns: {len(columns)}\n"

                # Sample rows
                sample_df = pd.read_sql(f"SELECT * FROM [{table}] LIMIT {sample_rows}", conn)
                if not sample_df.empty:
                    show_cols = list(sample_df.columns[:8])
                    display = sample_df[show_cols].copy()
                    for col in display.select_dtypes(include=["object"]).columns:
                        display[col] = display[col].astype(str).str[:25]
                    result += display.to_markdown(index=False)
                result += "\n\n"

            conn.close()

            size_mb = path.stat().st_size / 1024 / 1024
            result += f"Database size: {size_mb:.1f} MB"
            return result

        except Exception as e:
            return f"Error verifying database: {e}"


# =============================================================================
# Tool 6: gwdb_push_status
# =============================================================================

class GWDBPushStatusTool(BaseTool):
    """Show status of push operations."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="gwdb_push_status",
            description="Show the status of recent push operations, including tables pushed, row counts, and any errors.",
            category="gwdb_push",
            tags=["gwdb", "push", "status", "history"],
        ))

    def _execute(self, push_id: Optional[str] = None) -> str:
        with _approval_lock:
            if push_id:
                if push_id not in _push_status:
                    return f"Push '{push_id}' not found."
                status = _push_status[push_id]
                result = f"Push: {push_id}\n"
                result += f"Status: {status['status']}\n"
                result += f"Database: {status['db_path']}\n"
                if 'target_table' in status:
                    result += f"Table: {status['target_table']}\n"
                if 'rows_pushed' in status:
                    result += f"Rows: {status['rows_pushed']:,}\n"
                if 'error' in status:
                    result += f"Error: {status['error']}\n"
                return result

            if not _push_status:
                return "No push operations recorded in this session."

            result = "# Push History\n\n"
            for pid, status in _push_status.items():
                st = status["status"]
                rows = status.get("rows_pushed", "?")
                table = status.get("target_table", "?")
                result += f"- **{pid}**: {st} ({table}, {rows} rows) -> {status['db_path']}\n"

            return result
