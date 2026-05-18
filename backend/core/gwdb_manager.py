"""GWDB session manager — exposes DataFrame store state for the Studio UI."""

from typing import Any


def _get_store():
    """Get the GWDB DataFrame store from agent_os (lazy import)."""
    try:
        from agent_os.tools.library.gwdb_ingest import (
            list_dataframes,
            get_dataframe,
            get_store,
        )
        return list_dataframes, get_dataframe, get_store
    except ImportError:
        return None, None, None


def list_loaded_tables() -> list[dict[str, Any]]:
    """List all DataFrames currently loaded in the GWDB session store."""
    list_fn, _, _ = _get_store()
    if list_fn is None:
        return []

    tables = list_fn()
    result = []
    for name, info in tables.items():
        result.append({
            "name": name,
            "rows": info["rows"],
            "columns": info["columns"],
            "column_names": info["column_names"][:20],  # Cap for API response
            "memory_mb": info["memory_mb"],
        })
    return result


def get_table_info(table_name: str) -> dict[str, Any] | None:
    """Get detailed info about a loaded DataFrame."""
    _, get_fn, _ = _get_store()
    if get_fn is None:
        return None

    df = get_fn(table_name)
    if df is None:
        return None

    # Column details
    columns = []
    for col in df.columns:
        null_count = int(df[col].isnull().sum())
        columns.append({
            "name": col,
            "dtype": str(df[col].dtype),
            "null_count": null_count,
            "null_pct": round(null_count / len(df) * 100, 1) if len(df) > 0 else 0,
        })

    return {
        "name": table_name,
        "rows": len(df),
        "columns": len(df.columns),
        "column_details": columns,
        "memory_mb": round(df.memory_usage(deep=True).sum() / 1024 / 1024, 2),
    }


def clear_table(table_name: str) -> bool:
    """Remove a DataFrame from the session store."""
    _, _, store_fn = _get_store()
    if store_fn is None:
        return False

    store = store_fn()
    if table_name in store:
        del store[table_name]
        return True
    return False


def clear_all_tables() -> int:
    """Clear all DataFrames from the session store. Returns count cleared."""
    _, _, store_fn = _get_store()
    if store_fn is None:
        return 0

    store = store_fn()
    count = len(store)
    store.clear()
    return count


def get_approval_status() -> list[dict[str, Any]]:
    """Get status of GWDB push approval tokens."""
    try:
        from agent_os.tools.library.gwdb_push import _approval_tokens, _push_history
        import time

        tokens = []
        for token_id, record in _approval_tokens.items():
            elapsed = time.time() - record["timestamp"]
            tokens.append({
                "token": token_id[:12] + "...",
                "used": record["used"],
                "expired": elapsed > 300,
                "age_seconds": round(elapsed),
                "table_name": record.get("plan", {}).get("source_table", "unknown"),
            })

        history = []
        for entry in _push_history[-10:]:  # Last 10 pushes
            history.append({
                "timestamp": entry.get("timestamp", ""),
                "source_table": entry.get("source_table", ""),
                "target_tables": entry.get("target_tables", []),
                "rows_pushed": entry.get("rows_pushed", 0),
                "status": entry.get("status", "unknown"),
            })

        return {"tokens": tokens, "push_history": history}
    except (ImportError, AttributeError):
        return {"tokens": [], "push_history": []}
