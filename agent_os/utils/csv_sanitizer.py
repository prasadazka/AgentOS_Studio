"""
CSV Injection Prevention

Protects against formula injection attacks by prepending dangerous characters
(=, +, -, @, tab, CR) with a single quote to force text interpretation in
spreadsheet applications.
"""

from typing import Any, Dict, List, Optional, Union
import re

# Characters that can trigger formula injection
FORMULA_INJECTION_CHARS = frozenset(['=', '+', '-', '@', '\t', '\r'])


def is_dangerous_csv_value(value: Any) -> bool:
    """
    Check if a value could trigger CSV injection

    Args:
        value: Value to check

    Returns:
        True if value starts with dangerous character
    """
    if not isinstance(value, str):
        return False

    if not value:
        return False

    # Check if starts with dangerous character
    return value[0] in FORMULA_INJECTION_CHARS


def sanitize_csv_value(value: Any) -> str:
    """
    Sanitize a single CSV value to prevent injection

    Prepends single quote (') to values starting with dangerous characters.
    The quote makes spreadsheet applications treat the cell as text.

    Args:
        value: Value to sanitize (any type)

    Returns:
        Sanitized string value
    """
    # Convert to string
    if value is None:
        return ""

    str_value = str(value)

    # If starts with dangerous character, prepend single quote
    if is_dangerous_csv_value(str_value):
        return f"'{str_value}"

    return str_value


def sanitize_csv_row(row: Dict[str, Any]) -> Dict[str, str]:
    """
    Sanitize all values in a CSV row

    Args:
        row: Dictionary representing a CSV row

    Returns:
        Sanitized row with all values as strings
    """
    return {key: sanitize_csv_value(value) for key, value in row.items()}


def sanitize_csv_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Sanitize all rows in a CSV dataset

    Args:
        rows: List of dictionaries (CSV rows)

    Returns:
        List of sanitized rows
    """
    return [sanitize_csv_row(row) for row in rows]


def detect_injection_attempts(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze CSV data for potential injection attempts

    Useful for logging and security monitoring.

    Args:
        rows: List of CSV rows to analyze

    Returns:
        Dictionary with detection results:
        - dangerous_cells: Count of cells with dangerous characters
        - dangerous_rows: List of row indices with dangerous values
        - dangerous_columns: Dictionary of column names to dangerous value count
        - samples: List of example dangerous values (first 5)
    """
    dangerous_cells = 0
    dangerous_rows = []
    dangerous_columns: Dict[str, int] = {}
    samples = []

    for row_idx, row in enumerate(rows):
        row_has_dangerous = False

        for column, value in row.items():
            if is_dangerous_csv_value(value):
                dangerous_cells += 1
                row_has_dangerous = True

                # Track column
                dangerous_columns[column] = dangerous_columns.get(column, 0) + 1

                # Collect samples (first 5)
                if len(samples) < 5:
                    samples.append({
                        "row": row_idx,
                        "column": column,
                        "value": str(value)[:100]  # Limit length
                    })

        if row_has_dangerous:
            dangerous_rows.append(row_idx)

    return {
        "dangerous_cells": dangerous_cells,
        "dangerous_rows": dangerous_rows,
        "dangerous_columns": dangerous_columns,
        "samples": samples,
        "total_rows": len(rows),
        "affected_row_count": len(dangerous_rows)
    }
