"""Production-grade PDF extraction and processing tools"""

import hashlib
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import (
    ToolValidationError,
    ErrorCode
)
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Security Constants
# =============================================================================

MAX_PDF_SIZE_MB = 50
MAX_EXTRACT_CHARS = 10_000_000  # 10MB of text
BLOCKED_PATH_PATTERNS = ["/..", "\\.."]
SYSTEM_PATHS = ["/etc", "/sys", "/proc", "C:\\Windows", "C:\\Program Files"]


# =============================================================================
# Type-Safe Models
# =============================================================================

class PDFExtractInput(BaseModel):
    """Type-safe PDF extraction input with validation"""
    file_path: str = Field(..., min_length=1, max_length=1000)
    start_page: Optional[int] = Field(None, ge=0)
    end_page: Optional[int] = Field(None, ge=0)
    max_chars: Optional[int] = Field(None, gt=0, le=MAX_EXTRACT_CHARS)

    @field_validator('file_path')
    @classmethod
    def validate_file_path(cls, v):
        """Validate file path for security"""
        if not v or not v.strip():
            raise ValueError("File path cannot be empty")

        path_str = v.strip()

        # Block path traversal attempts
        for pattern in BLOCKED_PATH_PATTERNS:
            if pattern in path_str:
                raise ValueError(f"Path traversal detected: {pattern}")

        # Block system paths
        for sys_path in SYSTEM_PATHS:
            if path_str.startswith(sys_path):
                raise ValueError(f"Access to system path denied: {sys_path}")

        return path_str

    @field_validator('end_page')
    @classmethod
    def validate_page_range(cls, v, info):
        """Validate end_page >= start_page"""
        if v is not None and 'start_page' in info.data and info.data['start_page'] is not None:
            if v < info.data['start_page']:
                raise ValueError("end_page must be >= start_page")
        return v


class PDFExtractOutput(BaseModel):
    """Type-safe PDF extraction output"""
    success: bool
    file_name: Optional[str] = None
    total_pages: int = 0
    pages_extracted: Optional[Dict[str, int]] = None
    text: Optional[str] = None
    original_length: int = 0
    truncated: bool = False
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class PDFMetadataInput(BaseModel):
    """Type-safe PDF metadata input with validation"""
    file_path: str = Field(..., min_length=1, max_length=1000)

    @field_validator('file_path')
    @classmethod
    def validate_file_path(cls, v):
        """Validate file path for security"""
        if not v or not v.strip():
            raise ValueError("File path cannot be empty")

        path_str = v.strip()

        # Block path traversal attempts
        for pattern in BLOCKED_PATH_PATTERNS:
            if pattern in path_str:
                raise ValueError(f"Path traversal detected: {pattern}")

        # Block system paths
        for sys_path in SYSTEM_PATHS:
            if path_str.startswith(sys_path):
                raise ValueError(f"Access to system path denied: {sys_path}")

        return path_str


class PDFMetadataOutput(BaseModel):
    """Type-safe PDF metadata output"""
    success: bool
    file_name: Optional[str] = None
    total_pages: int = 0
    size_kb: float = 0.0
    metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Production-Grade PDF Tools
# =============================================================================

class PDFTextExtractorTool(BaseTool):
    """Production-grade PDF text extraction with validation

    Features:
    - Pydantic validation with size limits
    - Path traversal protection
    - File size limits (50MB max)
    - Structured logging with PII masking
    - Error handling with codes
    - Page range validation
    - Character truncation support
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="pdf_extract_text",
                description="Extract text content from PDF files. Production-grade with security validation.",
                category="data",
                tags=["pdf", "extraction", "documents"]
            )
        )

    def _execute(
        self,
        file_path: str,
        start_page: Optional[int] = None,
        end_page: Optional[int] = None,
        max_chars: Optional[int] = None
    ) -> str:
        """Extract text from PDF

        Args:
            file_path: Path to PDF file
            start_page: Starting page (0-indexed, optional)
            end_page: Ending page (0-indexed, optional)
            max_chars: Maximum characters to return (default: unlimited, max: 10MB)

        Returns:
            JSON with PDFExtractOutput schema
        """
        path_hash = hashlib.sha256(file_path.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = PDFExtractInput(
                file_path=file_path,
                start_page=start_page,
                end_page=end_page,
                max_chars=max_chars
            )

            logger.info("Extracting PDF text", extra={
                "path_hash": path_hash,
                "start_page": start_page,
                "end_page": end_page,
                "max_chars": max_chars
            })

            # Check file exists
            path = Path(validated.file_path)
            if not path.exists():
                logger.info("PDF file not found", extra={
                    "path_hash": path_hash
                })
                return PDFExtractOutput(
                    success=False,
                    error=f"File not found: {path.name}",
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                ).to_json()

            # Check file extension
            if not path.suffix.lower() == '.pdf':
                logger.info("Invalid file type", extra={
                    "path_hash": path_hash,
                    "suffix": path.suffix
                })
                return PDFExtractOutput(
                    success=False,
                    file_name=path.name,
                    error="File must be a PDF",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

            # Check file size
            file_size_mb = path.stat().st_size / (1024 * 1024)
            if file_size_mb > MAX_PDF_SIZE_MB:
                logger.warning("PDF file too large", extra={
                    "path_hash": path_hash,
                    "size_mb": file_size_mb,
                    "max_mb": MAX_PDF_SIZE_MB
                })
                return PDFExtractOutput(
                    success=False,
                    file_name=path.name,
                    error=f"PDF file too large: {file_size_mb:.2f}MB (max: {MAX_PDF_SIZE_MB}MB)",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

            # Import PyPDF2 here after validation
            try:
                from PyPDF2 import PdfReader
            except ImportError:
                logger.error("PyPDF2 not installed", extra={"path_hash": path_hash})
                return PDFExtractOutput(
                    success=False,
                    file_name=path.name,
                    error="PyPDF2 not installed. Install with: pip install PyPDF2",
                    error_code=ErrorCode.TOOL_DEPENDENCY_MISSING.value
                ).to_json()

            # Read PDF
            reader = PdfReader(str(path))
            num_pages = len(reader.pages)

            # Calculate page range
            start = validated.start_page if validated.start_page is not None else 0
            end = validated.end_page if validated.end_page is not None else num_pages

            # Clamp to valid range
            start = max(0, min(start, num_pages - 1))
            end = max(start + 1, min(end, num_pages))

            # Extract text
            text_parts = []
            for i in range(start, end):
                page = reader.pages[i]
                text_parts.append(f"--- Page {i + 1} ---\n{page.extract_text()}")

            full_text = "\n\n".join(text_parts)
            original_length = len(full_text)
            truncated = False

            # Apply character limit
            if validated.max_chars and len(full_text) > validated.max_chars:
                full_text = full_text[:validated.max_chars]
                truncated = True

            result = PDFExtractOutput(
                success=True,
                file_name=path.name,
                total_pages=num_pages,
                pages_extracted={
                    "start": start + 1,
                    "end": end
                },
                text=full_text,
                original_length=original_length,
                truncated=truncated
            )

            logger.info("PDF text extracted", extra={
                "path_hash": path_hash,
                "total_pages": num_pages,
                "pages_extracted": end - start,
                "text_length": len(full_text),
                "truncated": truncated,
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("PDF extraction validation failed", extra={"path_hash": path_hash}, exc_info=True)
            return PDFExtractOutput(
                success=False,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except ImportError as e:
            logger.error("PyPDF2 not installed", extra={"path_hash": path_hash})
            return PDFExtractOutput(
                success=False,
                error="PyPDF2 not installed. Install with: pip install PyPDF2",
                error_code=ErrorCode.TOOL_DEPENDENCY_MISSING.value
            ).to_json()

        except Exception as e:
            logger.error("PDF extraction failed", extra={"path_hash": path_hash}, exc_info=True)
            return PDFExtractOutput(
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class PDFMetadataTool(BaseTool):
    """Production-grade PDF metadata extraction with validation

    Features:
    - Pydantic validation with size limits
    - Path traversal protection
    - File size limits (50MB max)
    - Structured logging with PII masking
    - Error handling with codes
    - Safe metadata extraction
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="pdf_metadata",
                description="Extract metadata (title, author, pages, etc.) from PDF files. Production-grade with security validation.",
                category="data",
                tags=["pdf", "metadata"]
            )
        )

    def _execute(self, file_path: str) -> str:
        """Extract PDF metadata

        Args:
            file_path: Path to PDF file

        Returns:
            JSON with PDFMetadataOutput schema
        """
        path_hash = hashlib.sha256(file_path.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = PDFMetadataInput(file_path=file_path)

            logger.info("Extracting PDF metadata", extra={
                "path_hash": path_hash
            })

            # Check file exists
            path = Path(validated.file_path)
            if not path.exists():
                logger.info("PDF file not found", extra={
                    "path_hash": path_hash
                })
                return PDFMetadataOutput(
                    success=False,
                    error=f"File not found: {path.name}",
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                ).to_json()

            # Check file extension
            if not path.suffix.lower() == '.pdf':
                logger.info("Invalid file type", extra={
                    "path_hash": path_hash,
                    "suffix": path.suffix
                })
                return PDFMetadataOutput(
                    success=False,
                    file_name=path.name,
                    error="File must be a PDF",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

            # Check file size
            file_size_mb = path.stat().st_size / (1024 * 1024)
            if file_size_mb > MAX_PDF_SIZE_MB:
                logger.warning("PDF file too large", extra={
                    "path_hash": path_hash,
                    "size_mb": file_size_mb,
                    "max_mb": MAX_PDF_SIZE_MB
                })
                return PDFMetadataOutput(
                    success=False,
                    file_name=path.name,
                    error=f"PDF file too large: {file_size_mb:.2f}MB (max: {MAX_PDF_SIZE_MB}MB)",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

            # Import PyPDF2 here after validation
            try:
                from PyPDF2 import PdfReader
            except ImportError:
                logger.error("PyPDF2 not installed", extra={"path_hash": path_hash})
                return PDFMetadataOutput(
                    success=False,
                    file_name=path.name,
                    error="PyPDF2 not installed. Install with: pip install PyPDF2",
                    error_code=ErrorCode.TOOL_DEPENDENCY_MISSING.value
                ).to_json()

            # Read PDF
            reader = PdfReader(str(path))
            meta = reader.metadata

            # Build metadata dict
            metadata_fields = {}
            if meta:
                if meta.title:
                    metadata_fields["title"] = meta.title
                if meta.author:
                    metadata_fields["author"] = meta.author
                if meta.subject:
                    metadata_fields["subject"] = meta.subject
                if meta.creator:
                    metadata_fields["creator"] = meta.creator
                if meta.producer:
                    metadata_fields["producer"] = meta.producer
                if meta.creation_date:
                    metadata_fields["created"] = str(meta.creation_date)

            result = PDFMetadataOutput(
                success=True,
                file_name=path.name,
                total_pages=len(reader.pages),
                size_kb=round(path.stat().st_size / 1024, 2),
                metadata=metadata_fields if metadata_fields else None
            )

            logger.info("PDF metadata extracted", extra={
                "path_hash": path_hash,
                "total_pages": len(reader.pages),
                "has_metadata": bool(metadata_fields),
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("PDF metadata validation failed", extra={"path_hash": path_hash}, exc_info=True)
            return PDFMetadataOutput(
                success=False,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except ImportError as e:
            logger.error("PyPDF2 not installed", extra={"path_hash": path_hash})
            return PDFMetadataOutput(
                success=False,
                error="PyPDF2 not installed. Install with: pip install PyPDF2",
                error_code=ErrorCode.TOOL_DEPENDENCY_MISSING.value
            ).to_json()

        except Exception as e:
            logger.error("PDF metadata extraction failed", extra={"path_hash": path_hash}, exc_info=True)
            return PDFMetadataOutput(
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()
