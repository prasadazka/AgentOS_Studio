"""Production-grade file operations with security and validation"""

from pathlib import Path
from typing import Optional, Literal, List, Dict, Any
import json
import csv
import hashlib
import shutil

from pydantic import BaseModel, Field, validator

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import (
    ToolExecutionError,
    ToolValidationError,
    FilePermissionError,
    ErrorCode
)
from agent_os.utils.logging import get_logger
from agent_os.utils.csv_sanitizer import sanitize_csv_rows, detect_injection_attempts

logger = get_logger(__name__)


# =============================================================================
# Type-Safe Models
# =============================================================================

class FilePathInput(BaseModel):
    """Type-safe file path input with security validation"""
    file_path: str = Field(..., min_length=1)

    @validator('file_path')
    def validate_path(cls, v):
        """Validate file path for security"""
        if not v or not v.strip():
            raise ValueError("File path cannot be empty")

        path = Path(v).resolve()

        # Path traversal protection
        if ".." in str(path):
            raise ValueError("Path traversal not allowed")

        # Block access to sensitive system paths
        sensitive_paths = ['/etc', '/sys', '/proc', 'C:\\Windows', 'C:\\System32']
        path_str = str(path).replace('\\', '/')
        for sensitive in sensitive_paths:
            if path_str.startswith(sensitive):
                raise ValueError(f"Access to {sensitive} not allowed")

        return str(path)


class FileReadInput(FilePathInput):
    """Type-safe file read input"""
    encoding: str = Field("utf-8", pattern="^[a-zA-Z0-9_-]+$")
    max_chars: Optional[int] = Field(None, gt=0, le=10_000_000)  # 10MB limit


class FileWriteInput(FilePathInput):
    """Type-safe file write input"""
    content: str
    encoding: str = Field("utf-8", pattern="^[a-zA-Z0-9_-]+$")
    mode: Literal["write", "append"] = "write"
    create_dirs: bool = True

    @validator('content')
    def validate_content(cls, v):
        # Max 10MB content
        if len(v.encode('utf-8')) > 10_000_000:
            raise ValueError("Content exceeds 10MB limit")
        return v


class FileOutput(BaseModel):
    """Type-safe file operation output"""
    success: bool
    operation: str
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    content: Optional[str] = None
    size: Optional[int] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Production-Grade File Tools
# =============================================================================

class FileReaderTool(BaseTool):
    """Production-grade file reader with security and validation

    Security:
    - Path traversal protection
    - System path blocking
    - File size limits
    - Encoding validation
    """

    def __init__(self, max_file_size: int = 10_000_000):
        self.max_file_size = max_file_size
        super().__init__(
            ToolMetadata(
                name="file_read",
                description="Read any text file (returns full content). For CSV/TSV use csv_process instead (more efficient). For quick metadata use file_stats. REQUIRED param: file_path.",
                category="data",
                tags=["file", "io", "text"]
            )
        )

    def _execute(
        self,
        file_path: str,
        encoding: str = "utf-8",
        max_chars: Optional[int] = None
    ) -> str:
        """Read file content

        Args:
            file_path: Path to file
            encoding: File encoding (default: utf-8)
            max_chars: Max characters to return (max: 10MB)

        Returns:
            JSON with FileOutput schema
        """
        path_hash = hashlib.sha256(file_path.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = FileReadInput(
                file_path=file_path,
                encoding=encoding,
                max_chars=max_chars
            )

            path = Path(validated.file_path)

            if not path.exists():
                return FileOutput(
                    success=False,
                    operation="read",
                    file_path=file_path,
                    error="File not found",
                    error_code=ErrorCode.FILE_NOT_FOUND.value
                ).to_json()

            if not path.is_file():
                return FileOutput(
                    success=False,
                    operation="read",
                    file_path=file_path,
                    error="Path is not a file",
                    error_code=ErrorCode.FILE_ACCESS_ERROR.value
                ).to_json()

            # Check file size
            file_size = path.stat().st_size
            if file_size > self.max_file_size:
                size_mb = file_size / 1024 / 1024
                return FileOutput(
                    success=False,
                    operation="read",
                    file_path=file_path,
                    error=(
                        f"File too large: {size_mb:.1f} MB (max: {self.max_file_size // 1024 // 1024} MB). "
                        f"Use csv_process(file_path, max_rows=5) for CSV/TSV/TXT headers and sample rows, "
                        f"file_stats(file_path) for quick metadata, or "
                        f"gwdb_load_file(file_path) to load into memory for querying."
                    ),
                    error_code=ErrorCode.FILE_TOO_LARGE.value
                ).to_json()

            logger.info("Reading file", extra={
                "path_hash": path_hash,
                "encoding": validated.encoding,
                "file_size": file_size
            })

            # Read file with context manager
            with open(path, 'r', encoding=validated.encoding) as f:
                content = f.read()

            original_size = len(content)
            truncated = False

            if validated.max_chars and len(content) > validated.max_chars:
                content = content[:validated.max_chars]
                truncated = True

            logger.info("File read successfully", extra={
                "path_hash": path_hash,
                "content_size": len(content),
                "truncated": truncated
            })

            return FileOutput(
                success=True,
                operation="read",
                file_path=str(path),
                file_name=path.name,
                content=content,
                size=original_size,
                metadata={
                    "encoding": validated.encoding,
                    "truncated": truncated,
                    "displayed_chars": len(content),
                    "total_chars": original_size
                }
            ).to_json()

        except ToolValidationError as e:
            logger.error("Validation failed", extra={"path_hash": path_hash}, exc_info=True)
            return FileOutput(
                success=False,
                operation="read",
                file_path=file_path,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except UnicodeDecodeError:
            logger.error("Binary file detected", extra={"path_hash": path_hash})
            return FileOutput(
                success=False,
                operation="read",
                file_path=file_path,
                error="Binary file detected. Use specialized tool.",
                error_code=ErrorCode.FILE_ENCODING_ERROR.value
            ).to_json()

        except PermissionError:
            logger.error("Permission denied", extra={"path_hash": path_hash}, exc_info=True)
            return FileOutput(
                success=False,
                operation="read",
                file_path=file_path,
                error="Permission denied",
                error_code=ErrorCode.FILE_PERMISSION_DENIED.value
            ).to_json()

        except Exception as e:
            logger.error("Unexpected error", extra={"path_hash": path_hash}, exc_info=True)
            return FileOutput(
                success=False,
                operation="read",
                file_path=file_path,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class JSONProcessorTool(BaseTool):
    """Production-grade JSON processor with validation"""

    def __init__(self, max_file_size: int = 10_000_000):
        self.max_file_size = max_file_size
        super().__init__(
            ToolMetadata(
                name="json_process",
                description="Read and parse JSON files. USE THIS when user asks to read any .json file. Provide the file_path parameter.",
                category="data",
                tags=["json", "data", "parsing"]
            )
        )

    def _execute(
        self,
        file_path: str,
        query: Optional[str] = None
    ) -> str:
        """Read and process JSON

        Args:
            file_path: Path to JSON file
            query: Dot-notation query (e.g., 'data.users[0].name')

        Returns:
            JSON content or queried value
        """
        path_hash = hashlib.sha256(file_path.encode()).hexdigest()[:8]

        try:
            # Validate path
            validated = FilePathInput(file_path=file_path)
            path = Path(validated.file_path)

            if not path.exists():
                return FileOutput(
                    success=False,
                    operation="json_process",
                    file_path=file_path,
                    error="File not found",
                    error_code=ErrorCode.FILE_NOT_FOUND.value
                ).to_json()

            # Check file size
            file_size = path.stat().st_size
            if file_size > self.max_file_size:
                return FileOutput(
                    success=False,
                    operation="json_process",
                    error=f"File too large: {file_size} bytes",
                    error_code=ErrorCode.FILE_TOO_LARGE.value
                ).to_json()

            logger.info("Processing JSON", extra={
                "path_hash": path_hash,
                "has_query": bool(query)
            })

            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if query:
                result = self._query_json(data, query)
                content = json.dumps(result, indent=2)
            else:
                content = json.dumps(data, indent=2)

            logger.info("JSON processed", extra={"path_hash": path_hash})

            return FileOutput(
                success=True,
                operation="json_process",
                file_path=str(path),
                file_name=path.name,
                content=content,
                metadata={"query": query}
            ).to_json()

        except json.JSONDecodeError as e:
            logger.error("Invalid JSON", extra={"path_hash": path_hash}, exc_info=True)
            return FileOutput(
                success=False,
                operation="json_process",
                file_path=file_path,
                error=f"Invalid JSON: {str(e)}",
                error_code=ErrorCode.FILE_PARSE_ERROR.value
            ).to_json()

        except Exception as e:
            logger.error("Unexpected error", extra={"path_hash": path_hash}, exc_info=True)
            return FileOutput(
                success=False,
                operation="json_process",
                file_path=file_path,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()

    def _query_json(self, data, query: str):
        """Simple dot-notation query"""
        parts = query.split('.')
        result = data
        for part in parts:
            if '[' in part and ']' in part:
                key, idx = part.split('[')
                idx = int(idx.rstrip(']'))
                result = result[key][idx]
            else:
                result = result[part]
        return result


class CSVProcessorTool(BaseTool):
    """Production-grade CSV processor"""

    def __init__(self, max_file_size: int = 10_000_000):
        self.max_file_size = max_file_size
        super().__init__(
            ToolMetadata(
                name="csv_process",
                description="Read and preview CSV/TSV/TXT data files efficiently (only reads the requested rows, NOT the whole file). Auto-detects delimiter (comma, pipe, tab, semicolon). Returns headers, schema, and sample rows. Use max_rows=0 for headers only. REQUIRED param: file_path.",
                category="data",
                tags=["csv", "data", "tabular"]
            )
        )

    @staticmethod
    def _detect_delimiter(path: Path) -> str:
        """Auto-detect delimiter by sampling the first 4KB of the file."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                sample = f.read(4096)
            counts = {
                "|": sample.count("|"),
                ",": sample.count(","),
                "\t": sample.count("\t"),
                ";": sample.count(";"),
            }
            best = max(counts, key=counts.get)
            return best if counts[best] > 0 else ","
        except Exception:
            return ","

    def _execute(
        self,
        file_path: str,
        max_rows: Optional[int] = 10,
        delimiter: Optional[str] = None,
    ) -> str:
        """Read CSV/TSV/TXT file

        Args:
            file_path: Path to file
            max_rows: Max rows to return (default: 10)
            delimiter: CSV delimiter (default: ,)

        Returns:
            Formatted CSV preview
        """
        path_hash = hashlib.sha256(file_path.encode()).hexdigest()[:8]

        logger.debug(
            "csv_tool_received",
            file_path=file_path,
            file_path_length=len(file_path),
            max_rows=max_rows,
            delimiter=delimiter
        )

        try:
            validated = FilePathInput(file_path=file_path)
            path = Path(validated.file_path)

            logger.debug(
                "csv_tool_path_check",
                original_path=file_path,
                validated_path=str(path),
                path_exists=path.exists(),
                is_absolute=path.is_absolute()
            )

            # Validate file extension - only process CSV/TSV files
            valid_extensions = {'.csv', '.tsv', '.txt'}
            invalid_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.pdf', '.xlsx', '.xls', '.json', '.xml', '.zip', '.tar', '.gz'}

            file_ext = path.suffix.lower()
            if file_ext in invalid_extensions:
                return FileOutput(
                    success=False,
                    operation="csv_process",
                    error=f"Unsupported file type: {file_ext}. Use csv_process only for CSV/TSV files.",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

            if file_ext not in valid_extensions and file_ext != '':
                logger.warning(f"Unusual file extension for CSV: {file_ext}")

            if not path.exists():
                return FileOutput(
                    success=False,
                    operation="csv_process",
                    error="File not found",
                    error_code=ErrorCode.FILE_NOT_FOUND.value
                ).to_json()

            file_size = path.stat().st_size
            # No file size limit needed — we use pandas nrows to read only requested rows.
            # Even multi-GB files are safe since we never load the full file.

            # Auto-detect delimiter if not specified
            if delimiter is None:
                delimiter = self._detect_delimiter(path)

            logger.info("Processing CSV", extra={"path_hash": path_hash, "max_rows": max_rows, "delimiter": delimiter})

            # Use pandas for efficient reading: only read needed rows + get total count
            # This avoids loading entire file into memory for large CSVs
            effective_nrows = max_rows if max_rows and max_rows > 0 else 0

            try:
                import pandas as pd

                if effective_nrows > 0:
                    # Read only the rows we need (nrows) — O(max_rows) not O(total)
                    df_sample = pd.read_csv(
                        path, delimiter=delimiter, nrows=effective_nrows,
                        encoding="utf-8", on_bad_lines="skip"
                    )
                else:
                    # Headers only — read 0 data rows
                    df_sample = pd.read_csv(
                        path, delimiter=delimiter, nrows=0,
                        encoding="utf-8", on_bad_lines="skip"
                    )

                columns = list(df_sample.columns)

                # Get total row count efficiently (count newlines, don't parse)
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    total_rows = sum(1 for _ in f) - 1  # subtract header

                displayed_rows = df_sample.to_dict(orient="records")
                truncated = total_rows > len(displayed_rows)

            except ImportError:
                # Fallback: vanilla csv — but only read max_rows + header, not whole file
                with open(path, 'r', encoding='utf-8', newline='') as f:
                    reader = csv.DictReader(f, delimiter=delimiter)
                    displayed_rows = []
                    if effective_nrows > 0:
                        for i, row in enumerate(reader):
                            if i >= effective_nrows:
                                break
                            displayed_rows.append(row)
                    # Count remaining rows without storing them
                    remaining = sum(1 for _ in reader)

                # Get columns from header even if no data rows read
                if not displayed_rows and effective_nrows == 0:
                    # Re-read just the header line
                    with open(path, 'r', encoding='utf-8', newline='') as f:
                        header_reader = csv.reader(f, delimiter=delimiter)
                        try:
                            columns = next(header_reader)
                        except StopIteration:
                            columns = []
                    total_rows = remaining
                    truncated = total_rows > 0
                elif not displayed_rows:
                    return FileOutput(
                        success=True,
                        operation="csv_process",
                        file_path=str(path),
                        file_name=path.name,
                        content=json.dumps({"rows": [], "message": "Empty CSV"}),
                        metadata={"total_rows": 0}
                    ).to_json()
                else:
                    columns = list(displayed_rows[0].keys())
                    total_rows = len(displayed_rows) + remaining
                    truncated = remaining > 0

            # Sanitize CSV data to prevent formula injection
            sanitized_rows = sanitize_csv_rows(displayed_rows)

            # Detect injection attempts for logging/monitoring
            injection_analysis = detect_injection_attempts(displayed_rows)
            if injection_analysis["dangerous_cells"] > 0:
                logger.warning(
                    "CSV injection attempt detected and sanitized",
                    extra={
                        "path_hash": path_hash,
                        "dangerous_cells": injection_analysis["dangerous_cells"],
                        "affected_rows": injection_analysis["affected_row_count"],
                        "dangerous_columns": list(injection_analysis["dangerous_columns"].keys())
                    }
                )

            result_data = {
                "schema": {
                    "available_columns": columns
                },
                "file": path.name,
                "total_rows": total_rows,
                "columns": columns,
                "rows": sanitized_rows,
                "truncated": truncated,
                "rows_hidden": total_rows - len(displayed_rows) if truncated else 0,
                "security": {
                    "injection_prevention": True,
                    "dangerous_cells_sanitized": injection_analysis["dangerous_cells"]
                }
            }

            logger.info("CSV processed", extra={"path_hash": path_hash, "rows": total_rows})

            return FileOutput(
                success=True,
                operation="csv_process",
                file_path=str(path),
                file_name=path.name,
                content=json.dumps(result_data, indent=2),
                metadata={"total_rows": total_rows, "delimiter": delimiter}
            ).to_json()

        except Exception as e:
            logger.error("Unexpected error", extra={"path_hash": path_hash}, exc_info=True)
            return FileOutput(
                success=False,
                operation="csv_process",
                file_path=file_path,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class FileWriterTool(BaseTool):
    """Production-grade file writer with validation"""

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="file_write",
                description="Write or create a text file. USE THIS when user asks to 'write', 'create', 'save', or 'make' a file. Required params: file_path (full path to file), content (text to write).",
                category="data",
                tags=["file", "io", "write", "create"]
            )
        )

    def _execute(
        self,
        file_path: str,
        content: str,
        encoding: str = "utf-8",
        mode: Literal["write", "append"] = "write",
        create_dirs: bool = True
    ) -> str:
        """Write content to file

        Args:
            file_path: Path to file
            content: Content to write (max 10MB)
            encoding: File encoding
            mode: 'write' (overwrite) or 'append'
            create_dirs: Create parent directories

        Returns:
            JSON with FileOutput schema
        """
        path_hash = hashlib.sha256(file_path.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = FileWriteInput(
                file_path=file_path,
                content=content,
                encoding=encoding,
                mode=mode,
                create_dirs=create_dirs
            )

            path = Path(validated.file_path)

            logger.info("Writing file", extra={
                "path_hash": path_hash,
                "mode": mode,
                "content_size": len(content)
            })

            # Create directories
            if validated.create_dirs and not path.parent.exists():
                path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            file_mode = 'a' if mode == "append" else 'w'
            with open(path, file_mode, encoding=validated.encoding) as f:
                f.write(validated.content)

            file_size = path.stat().st_size

            logger.info("File written", extra={
                "path_hash": path_hash,
                "file_size": file_size
            })

            return FileOutput(
                success=True,
                operation=mode,
                file_path=str(path),
                file_name=path.name,
                metadata={
                    "bytes_written": len(content.encode(validated.encoding)),
                    "total_file_size": file_size,
                    "encoding": validated.encoding
                }
            ).to_json()

        except ToolValidationError as e:
            logger.error("Validation failed", extra={"path_hash": path_hash}, exc_info=True)
            return FileOutput(
                success=False,
                operation="write",
                file_path=file_path,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except PermissionError:
            logger.error("Permission denied", extra={"path_hash": path_hash}, exc_info=True)
            return FileOutput(
                success=False,
                operation="write",
                file_path=file_path,
                error="Permission denied",
                error_code=ErrorCode.FILE_PERMISSION_DENIED.value
            ).to_json()

        except Exception as e:
            logger.error("Unexpected error", extra={"path_hash": path_hash}, exc_info=True)
            return FileOutput(
                success=False,
                operation="write",
                file_path=file_path,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class FileDeleterTool(BaseTool):
    """Production-grade file deleter with safety checks"""

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="file_delete",
                description="Delete a file or folder. USE THIS when user asks to 'delete', 'remove', or 'rm' a file. Required param: file_path (full path to file).",
                category="data",
                tags=["file", "io", "delete", "remove"]
            )
        )

    def _execute(
        self,
        file_path: str,
        recursive: bool = False
    ) -> str:
        """Delete file or directory

        Args:
            file_path: Path to file or directory
            recursive: Delete directories recursively

        Returns:
            JSON with FileOutput schema
        """
        path_hash = hashlib.sha256(file_path.encode()).hexdigest()[:8]

        try:
            validated = FilePathInput(file_path=file_path)
            path = Path(validated.file_path)

            if not path.exists():
                return FileOutput(
                    success=False,
                    operation="delete",
                    file_path=file_path,
                    error="Path does not exist",
                    error_code=ErrorCode.FILE_NOT_FOUND.value
                ).to_json()

            is_directory = path.is_dir()
            file_size = 0
            file_count = 0

            if is_directory:
                if not recursive:
                    return FileOutput(
                        success=False,
                        operation="delete",
                        file_path=file_path,
                        error="Path is directory. Set recursive=True.",
                        error_code=ErrorCode.FILE_ACCESS_ERROR.value
                    ).to_json()

                file_count = sum(1 for _ in path.rglob('*') if _.is_file())
                logger.info("Deleting directory", extra={
                    "path_hash": path_hash,
                    "file_count": file_count
                })
                shutil.rmtree(path)
            else:
                file_size = path.stat().st_size
                logger.info("Deleting file", extra={
                    "path_hash": path_hash,
                    "file_size": file_size
                })
                path.unlink()

            logger.info("Deletion completed", extra={"path_hash": path_hash})

            return FileOutput(
                success=True,
                operation="delete",
                file_path=str(path),
                metadata={
                    "was_directory": is_directory,
                    "file_size": file_size if not is_directory else None,
                    "files_deleted": file_count if is_directory else 1
                }
            ).to_json()

        except PermissionError:
            logger.error("Permission denied", extra={"path_hash": path_hash}, exc_info=True)
            return FileOutput(
                success=False,
                operation="delete",
                file_path=file_path,
                error="Permission denied",
                error_code=ErrorCode.FILE_PERMISSION_DENIED.value
            ).to_json()

        except Exception as e:
            logger.error("Unexpected error", extra={"path_hash": path_hash}, exc_info=True)
            return FileOutput(
                success=False,
                operation="delete",
                file_path=file_path,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class DirectoryListTool(BaseTool):
    """Production-grade directory listing"""

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="directory_list",
                description="List files and folders in a directory. USE THIS to find/search for files. Params: directory_path (default '.'), pattern (glob like '*.txt' or '*config*'), recursive (True to search subfolders).",
                category="data",
                tags=["directory", "file", "list", "ls", "search", "find"]
            )
        )

    def _execute(
        self,
        directory_path: str = ".",
        pattern: Optional[str] = "*",
        recursive: bool = False,
        include_hidden: bool = False,
        max_items: Optional[int] = 100
    ) -> str:
        """List directory contents

        Args:
            directory_path: Path to directory
            pattern: Glob pattern (default: *)
            recursive: List recursively
            include_hidden: Include hidden files
            max_items: Max items to return (default: 100)

        Returns:
            JSON with FileOutput schema
        """
        try:
            validated = FilePathInput(file_path=directory_path)
            path = Path(validated.file_path)

            if not path.exists():
                return FileOutput(
                    success=False,
                    operation="list",
                    error="Directory does not exist",
                    error_code=ErrorCode.FILE_NOT_FOUND.value
                ).to_json()

            if not path.is_dir():
                return FileOutput(
                    success=False,
                    operation="list",
                    error="Path is not a directory",
                    error_code=ErrorCode.FILE_ACCESS_ERROR.value
                ).to_json()

            logger.info("Listing directory", extra={
                "pattern": pattern,
                "recursive": recursive
            })

            # Handle None pattern - default to "*" to list all items
            if pattern is None:
                pattern = "*"

            items = list(path.rglob(pattern)) if recursive else list(path.glob(pattern))

            if not include_hidden:
                items = [item for item in items if not item.name.startswith('.')]

            total_items = len(items)
            if max_items:
                items = items[:max_items]

            entries = []
            for item in items:
                try:
                    stat = item.stat()
                    entry = {
                        "name": item.name,
                        "path": str(item),
                        "type": "directory" if item.is_dir() else "file",
                        "size": stat.st_size if item.is_file() else None,
                        "modified": stat.st_mtime
                    }
                    if item.is_file():
                        entry["extension"] = item.suffix
                    entries.append(entry)
                except (PermissionError, OSError):
                    continue

            result_data = {
                "directory": str(path),
                "total_items": total_items,
                "returned_items": len(entries),
                "truncated": total_items > len(entries),
                "pattern": pattern,
                "entries": entries
            }

            logger.info("Directory listed", extra={"total_items": total_items})

            return FileOutput(
                success=True,
                operation="list",
                file_path=str(path),
                content=json.dumps(result_data, indent=2),
                metadata={"total_items": total_items, "returned_items": len(entries)}
            ).to_json()

        except Exception as e:
            logger.error("Unexpected error", exc_info=True)
            return FileOutput(
                success=False,
                operation="list",
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()
