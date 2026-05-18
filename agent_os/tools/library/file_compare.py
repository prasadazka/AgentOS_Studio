"""File Comparison Tools - Compare files without reading full content into LLM context.

Performs diffing, structural comparison, and data comparison in Python,
returning only a concise summary to the LLM. This saves massive token usage
compared to having the agent read both files and compare them itself.
"""

import csv
import difflib
import hashlib
import json
from pathlib import Path
from typing import Optional

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)

# Max file size for comparison (50MB)
MAX_COMPARE_SIZE = 50_000_000


def _read_file_safe(path: Path, encoding: str = "utf-8") -> tuple:
    """Read file with size and existence checks. Returns (content, error)."""
    if not path.exists():
        return None, f"File not found: {path}"
    if not path.is_file():
        return None, f"Not a file: {path}"
    size = path.stat().st_size
    if size > MAX_COMPARE_SIZE:
        return None, f"File too large: {size:,} bytes (max {MAX_COMPARE_SIZE:,})"
    try:
        return path.read_text(encoding=encoding, errors="replace"), None
    except Exception as e:
        return None, f"Error reading {path.name}: {e}"


def _file_meta(path: Path) -> dict:
    """Get basic file metadata."""
    stat = path.stat()
    return {
        "name": path.name,
        "size": stat.st_size,
        "ext": path.suffix.lower(),
    }


# =============================================================================
# Tool 1: file_compare (general text/data diff)
# =============================================================================

class FileCompareTool(BaseTool):
    """Compare two files and return a concise diff summary."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="file_compare",
            description=(
                "Compare two files and return a summary of differences. "
                "Works with text, CSV, JSON, and other files. "
                "Returns ONLY the diff summary (not full file contents), saving tokens. "
                "Modes: 'auto' (detect from extension), 'text' (line-by-line diff), "
                "'csv' (row/column diff), 'json' (structural diff), 'binary' (hash comparison). "
                "Example: file_compare(file_a='/path/a.csv', file_b='/path/b.csv')"
            ),
            category="data",
            tags=["file", "compare", "diff", "data"],
        ))

    def _execute(
        self,
        file_a: str,
        file_b: str,
        mode: str = "auto",
        encoding: str = "utf-8",
        max_diff_lines: int = 50,
        context_lines: int = 3,
    ) -> str:
        path_a = Path(file_a)
        path_b = Path(file_b)

        # Auto-detect mode from extension
        if mode == "auto":
            ext = path_a.suffix.lower()
            if ext in (".csv", ".tsv", ".txt"):
                # Check if it looks like tabular data
                if ext in (".csv", ".tsv"):
                    mode = "csv"
                else:
                    mode = "text"
            elif ext == ".json":
                mode = "json"
            elif ext in (".xlsx", ".xls", ".parquet", ".db", ".sqlite"):
                mode = "binary"
            else:
                mode = "text"

        if mode == "csv":
            return self._compare_csv(path_a, path_b, encoding, max_diff_lines)
        elif mode == "json":
            return self._compare_json(path_a, path_b, encoding)
        elif mode == "binary":
            return self._compare_binary(path_a, path_b)
        else:
            return self._compare_text(path_a, path_b, encoding, max_diff_lines, context_lines)

    def _compare_text(self, path_a, path_b, encoding, max_diff_lines, context_lines):
        """Line-by-line text diff."""
        content_a, err = _read_file_safe(path_a, encoding)
        if err:
            return f"Error: {err}"
        content_b, err = _read_file_safe(path_b, encoding)
        if err:
            return f"Error: {err}"

        lines_a = content_a.splitlines(keepends=True)
        lines_b = content_b.splitlines(keepends=True)

        # Quick identity check
        if content_a == content_b:
            return (
                f"Files are IDENTICAL.\n"
                f"- {path_a.name}: {len(lines_a):,} lines, {len(content_a):,} chars\n"
                f"- {path_b.name}: {len(lines_b):,} lines, {len(content_b):,} chars"
            )

        # Generate unified diff
        diff = list(difflib.unified_diff(
            lines_a, lines_b,
            fromfile=path_a.name, tofile=path_b.name,
            n=context_lines
        ))

        # Count changes
        added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
        changed_regions = sum(1 for l in diff if l.startswith("@@"))

        result = f"# Text Diff: {path_a.name} vs {path_b.name}\n\n"
        result += f"- File A: {len(lines_a):,} lines, {len(content_a):,} chars\n"
        result += f"- File B: {len(lines_b):,} lines, {len(content_b):,} chars\n"
        result += f"- Lines added: {added:,}\n"
        result += f"- Lines removed: {removed:,}\n"
        result += f"- Changed regions: {changed_regions}\n\n"

        # Show diff (truncated)
        if len(diff) <= max_diff_lines:
            result += "```diff\n" + "".join(diff) + "```\n"
        else:
            result += f"```diff\n{''.join(diff[:max_diff_lines])}```\n"
            result += f"\n... {len(diff) - max_diff_lines} more diff lines (showing first {max_diff_lines})\n"

        return result

    def _compare_csv(self, path_a, path_b, encoding, max_diff_lines):
        """Structured CSV comparison: schema + row-level diff."""
        content_a, err = _read_file_safe(path_a, encoding)
        if err:
            return f"Error: {err}"
        content_b, err = _read_file_safe(path_b, encoding)
        if err:
            return f"Error: {err}"

        # Detect delimiter
        def detect_delim(content):
            sample = content[:4096]
            counts = {",": sample.count(","), "\t": sample.count("\t"),
                      "|": sample.count("|"), ";": sample.count(";")}
            return max(counts, key=counts.get)

        delim_a = detect_delim(content_a)
        delim_b = detect_delim(content_b)

        lines_a = content_a.splitlines()
        lines_b = content_b.splitlines()

        reader_a = csv.reader(lines_a, delimiter=delim_a)
        reader_b = csv.reader(lines_b, delimiter=delim_b)

        rows_a = list(reader_a)
        rows_b = list(reader_b)

        if not rows_a or not rows_b:
            return "Error: One or both files are empty."

        headers_a = rows_a[0] if rows_a else []
        headers_b = rows_b[0] if rows_b else []
        data_a = rows_a[1:]
        data_b = rows_b[1:]

        result = f"# CSV Comparison: {path_a.name} vs {path_b.name}\n\n"

        # Schema comparison
        result += "## Schema\n"
        result += f"- File A: {len(headers_a)} columns, {len(data_a):,} rows (delimiter='{delim_a}')\n"
        result += f"- File B: {len(headers_b)} columns, {len(data_b):,} rows (delimiter='{delim_b}')\n"

        set_a = set(headers_a)
        set_b = set(headers_b)
        common = set_a & set_b
        only_a = set_a - set_b
        only_b = set_b - set_a

        result += f"- Common columns: {len(common)}\n"
        if only_a:
            result += f"- Only in A: {', '.join(sorted(only_a))}\n"
        if only_b:
            result += f"- Only in B: {', '.join(sorted(only_b))}\n"

        if headers_a == headers_b:
            result += "- Column order: SAME\n"
        elif set_a == set_b:
            result += "- Column order: DIFFERENT (same columns, different order)\n"

        # Row comparison (on common columns)
        result += "\n## Data\n"
        if data_a == data_b:
            result += "Row data is IDENTICAL.\n"
            return result

        result += f"- Row count difference: {len(data_a):,} vs {len(data_b):,}"
        if len(data_a) != len(data_b):
            result += f" (delta: {len(data_b) - len(data_a):+,})\n"
        else:
            result += "\n"

        # Compare row-by-row for matching column sets
        if headers_a == headers_b:
            diff_rows = 0
            sample_diffs = []
            max_compare = min(len(data_a), len(data_b))
            for i in range(max_compare):
                if data_a[i] != data_b[i]:
                    diff_rows += 1
                    if len(sample_diffs) < 5:
                        # Find which columns differ
                        col_diffs = []
                        for j, (va, vb) in enumerate(zip(data_a[i], data_b[i])):
                            if va != vb:
                                col_name = headers_a[j] if j < len(headers_a) else f"col_{j}"
                                col_diffs.append(f"{col_name}: '{va[:30]}' -> '{vb[:30]}'")
                        sample_diffs.append(f"  Row {i+2}: {', '.join(col_diffs[:3])}")

            result += f"- Rows with differences: {diff_rows:,} (of {max_compare:,} compared)\n"

            # Extra rows
            if len(data_a) > len(data_b):
                result += f"- {len(data_a) - len(data_b):,} extra rows in A (not in B)\n"
            elif len(data_b) > len(data_a):
                result += f"- {len(data_b) - len(data_a):,} extra rows in B (not in A)\n"

            if sample_diffs:
                result += "\nSample differences:\n"
                result += "\n".join(sample_diffs) + "\n"
                if diff_rows > 5:
                    result += f"  ... and {diff_rows - 5} more rows differ\n"
        else:
            result += "- Columns differ; row-by-row comparison skipped.\n"

        return result

    def _compare_json(self, path_a, path_b, encoding):
        """Structural JSON comparison."""
        content_a, err = _read_file_safe(path_a, encoding)
        if err:
            return f"Error: {err}"
        content_b, err = _read_file_safe(path_b, encoding)
        if err:
            return f"Error: {err}"

        try:
            data_a = json.loads(content_a)
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON in {path_a.name}: {e}"
        try:
            data_b = json.loads(content_b)
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON in {path_b.name}: {e}"

        result = f"# JSON Comparison: {path_a.name} vs {path_b.name}\n\n"

        if data_a == data_b:
            result += "Files are IDENTICAL (structurally equal).\n"
            return result

        # Type comparison
        type_a = type(data_a).__name__
        type_b = type(data_b).__name__
        result += f"- File A: {type_a}"
        result += f" ({len(data_a)} items)\n" if isinstance(data_a, (list, dict)) else "\n"
        result += f"- File B: {type_b}"
        result += f" ({len(data_b)} items)\n" if isinstance(data_b, (list, dict)) else "\n"

        if type_a != type_b:
            result += f"\nRoot types differ: {type_a} vs {type_b}\n"
            return result

        # Dict comparison
        if isinstance(data_a, dict) and isinstance(data_b, dict):
            keys_a = set(data_a.keys())
            keys_b = set(data_b.keys())
            common = keys_a & keys_b
            only_a = keys_a - keys_b
            only_b = keys_b - keys_a

            result += f"\n## Keys\n"
            result += f"- Common keys: {len(common)}\n"
            if only_a:
                result += f"- Only in A: {', '.join(sorted(list(only_a)[:20]))}"
                if len(only_a) > 20:
                    result += f" ... +{len(only_a)-20} more"
                result += "\n"
            if only_b:
                result += f"- Only in B: {', '.join(sorted(list(only_b)[:20]))}"
                if len(only_b) > 20:
                    result += f" ... +{len(only_b)-20} more"
                result += "\n"

            # Value differences on common keys
            val_diffs = []
            for k in sorted(common):
                if data_a[k] != data_b[k]:
                    val_diffs.append(k)

            result += f"- Keys with different values: {len(val_diffs)}\n"
            if val_diffs:
                result += "\nChanged keys (sample):\n"
                for k in val_diffs[:10]:
                    va = str(data_a[k])[:50]
                    vb = str(data_b[k])[:50]
                    result += f"  {k}: '{va}' -> '{vb}'\n"
                if len(val_diffs) > 10:
                    result += f"  ... and {len(val_diffs) - 10} more\n"

        # List comparison
        elif isinstance(data_a, list) and isinstance(data_b, list):
            result += f"\n## Array\n"
            result += f"- Length A: {len(data_a):,}\n"
            result += f"- Length B: {len(data_b):,}\n"

            if len(data_a) == len(data_b):
                diffs = sum(1 for a, b in zip(data_a, data_b) if a != b)
                result += f"- Elements that differ: {diffs:,}\n"
            else:
                result += f"- Length difference: {len(data_b) - len(data_a):+,}\n"

        return result

    def _compare_binary(self, path_a, path_b):
        """Binary/hash comparison for non-text files."""
        for p in [path_a, path_b]:
            if not p.exists():
                return f"Error: File not found: {p}"

        meta_a = _file_meta(path_a)
        meta_b = _file_meta(path_b)

        # Compute hashes
        def file_hash(path):
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()

        hash_a = file_hash(path_a)
        hash_b = file_hash(path_b)

        result = f"# Binary Comparison: {path_a.name} vs {path_b.name}\n\n"
        result += f"- File A: {meta_a['size']:,} bytes ({meta_a['ext']})\n"
        result += f"- File B: {meta_b['size']:,} bytes ({meta_b['ext']})\n"
        result += f"- Size difference: {meta_b['size'] - meta_a['size']:+,} bytes\n"
        result += f"- SHA256 A: {hash_a[:16]}...\n"
        result += f"- SHA256 B: {hash_b[:16]}...\n"
        result += f"- Identical: {'YES' if hash_a == hash_b else 'NO'}\n"

        return result


# =============================================================================
# Tool 2: file_stats (quick stats without reading full content)
# =============================================================================

class FileStatsTool(BaseTool):
    """Get file statistics without reading content into LLM context."""

    def __init__(self):
        super().__init__(ToolMetadata(
            name="file_stats",
            description=(
                "Get file statistics (size, line count, word count, encoding, hash) "
                "WITHOUT reading the full content. Useful for quick checks before "
                "deciding whether to read or compare files. "
                "Example: file_stats(file_path='/path/to/data.csv')"
            ),
            category="data",
            tags=["file", "stats", "info", "metadata"],
        ))

    def _execute(self, file_path: str, encoding: str = "utf-8") -> str:
        path = Path(file_path)

        if not path.exists():
            return f"Error: File not found: {path}"
        if not path.is_file():
            return f"Error: Not a file: {path}"

        stat = path.stat()
        size = stat.st_size
        ext = path.suffix.lower()

        result = f"# File Stats: {path.name}\n\n"
        result += f"- Path: {path}\n"
        result += f"- Size: {size:,} bytes ({size/1024:.1f} KB)\n"
        result += f"- Extension: {ext}\n"

        # For text files, count lines efficiently without loading all into memory.
        # No file size limit here — we stream in chunks, never load the full file.
        text_exts = {".txt", ".csv", ".tsv", ".json", ".md", ".log", ".py",
                     ".js", ".yaml", ".yml", ".xml", ".html", ".sql"}
        if ext in text_exts:
            try:
                # Count lines efficiently (stream, don't load all)
                line_count = 0
                with open(path, "r", encoding=encoding, errors="replace") as f:
                    # Read first 4KB for sampling (delimiter detection, header)
                    sample = f.read(4096)
                    first_lines = sample.splitlines()
                    # Count remaining lines
                    line_count = len(first_lines)
                    for chunk in iter(lambda: f.read(65536), ""):
                        line_count += chunk.count("\n")

                result += f"- Lines: {line_count:,}\n"

                # For tabular files (CSV, TSV, TXT), detect delimiter and show headers
                tabular_exts = {".csv", ".tsv", ".txt"}
                if ext in tabular_exts and first_lines:
                    # Auto-detect delimiter from sample
                    counts = {
                        ",": sample.count(","),
                        "\t": sample.count("\t"),
                        "|": sample.count("|"),
                        ";": sample.count(";"),
                    }
                    best_delim = max(counts, key=counts.get)

                    # Only treat as tabular if delimiter appears consistently
                    if counts[best_delim] > 0:
                        reader = csv.reader(first_lines[:2], delimiter=best_delim)
                        rows = list(reader)
                        if rows and len(rows[0]) > 1:  # at least 2 columns = tabular
                            result += f"- Format: tabular (delimiter='{best_delim}')\n"
                            result += f"- Columns: {len(rows[0])}\n"
                            result += f"- Headers: {', '.join(rows[0][:15])}"
                            if len(rows[0]) > 15:
                                result += f" ... +{len(rows[0])-15} more"
                            result += "\n"
                            result += f"- Data rows: {line_count - 1:,}\n"
                        else:
                            # Single-column or plain text
                            result += f"- Format: plain text\n"
                    else:
                        result += f"- Format: plain text\n"

                # For JSON, add structure info (only parse if under 100MB)
                elif ext == ".json":
                    if size > 100_000_000:
                        result += f"- JSON: too large to parse ({size/1024/1024:.0f} MB)\n"
                    else:
                        try:
                            json_content = path.read_text(encoding=encoding, errors="replace")
                            data = json.loads(json_content)
                            dtype = type(data).__name__
                            result += f"- JSON type: {dtype}\n"
                            if isinstance(data, list):
                                result += f"- Array length: {len(data):,}\n"
                            elif isinstance(data, dict):
                                result += f"- Top-level keys: {len(data)}\n"
                                keys = list(data.keys())[:10]
                                result += f"- Keys: {', '.join(keys)}"
                                if len(data) > 10:
                                    result += f" ... +{len(data)-10} more"
                                result += "\n"
                        except json.JSONDecodeError:
                            result += "- JSON: invalid/malformed\n"
            except Exception as e:
                result += f"- Error reading content: {e}\n"
        else:
            # Binary file — just hash
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            result += f"- SHA256: {h.hexdigest()[:32]}...\n"

        return result
