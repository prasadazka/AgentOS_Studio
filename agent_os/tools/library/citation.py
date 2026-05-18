"""Production-grade citation generation tools"""

import hashlib
from typing import Optional, Literal, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
import re

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

MIN_YEAR = 1800
MAX_YEAR = datetime.now().year + 10  # Allow future publications
MAX_TITLE_LENGTH = 500
MAX_AUTHORS_LENGTH = 1000
MAX_JOURNAL_LENGTH = 200
MAX_VOLUME_LENGTH = 50
MAX_PAGES_LENGTH = 50
MAX_DOI_LENGTH = 200
MAX_URL_LENGTH = 2000

# Basic DOI pattern (10.xxxx/yyyy)
DOI_PATTERN = r'^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$'

# Basic URL pattern (http:// or https://)
URL_PATTERN = r'^https?://.+'


# =============================================================================
# Type-Safe Models
# =============================================================================

CitationStyle = Literal["apa", "mla", "chicago", "ieee", "bibtex"]


class CitationGenerateInput(BaseModel):
    """Type-safe citation generation input with validation"""
    title: str = Field(..., min_length=1, max_length=MAX_TITLE_LENGTH)
    authors: str = Field(..., min_length=1, max_length=MAX_AUTHORS_LENGTH)
    year: int = Field(..., ge=MIN_YEAR, le=MAX_YEAR)
    style: CitationStyle = "apa"
    journal: Optional[str] = Field(None, max_length=MAX_JOURNAL_LENGTH)
    volume: Optional[str] = Field(None, max_length=MAX_VOLUME_LENGTH)
    pages: Optional[str] = Field(None, max_length=MAX_PAGES_LENGTH)
    doi: Optional[str] = Field(None, max_length=MAX_DOI_LENGTH)
    url: Optional[str] = Field(None, max_length=MAX_URL_LENGTH)

    @field_validator('title')
    @classmethod
    def validate_title(cls, v):
        """Validate title content"""
        if not v or not v.strip():
            raise ValueError("Title cannot be empty")
        return v.strip()

    @field_validator('authors')
    @classmethod
    def validate_authors(cls, v):
        """Validate authors content"""
        if not v or not v.strip():
            raise ValueError("Authors cannot be empty")

        # Check for template injection patterns
        dangerous_patterns = ['{%', '{{', '<%', '${']
        for pattern in dangerous_patterns:
            if pattern in v:
                raise ValueError(f"Potentially dangerous pattern detected: {pattern}")

        return v.strip()

    @field_validator('doi')
    @classmethod
    def validate_doi(cls, v):
        """Validate DOI format"""
        if v is None:
            return v

        v = v.strip()
        if not v:
            return None

        # Remove common prefixes
        if v.startswith('https://doi.org/'):
            v = v.replace('https://doi.org/', '')
        elif v.startswith('http://doi.org/'):
            v = v.replace('http://doi.org/', '')
        elif v.startswith('doi:'):
            v = v.replace('doi:', '')

        # Validate DOI pattern
        if not re.match(DOI_PATTERN, v):
            raise ValueError(f"Invalid DOI format: {v}. Expected format: 10.xxxx/yyyy")

        return v

    @field_validator('url')
    @classmethod
    def validate_url(cls, v):
        """Validate URL format"""
        if v is None:
            return v

        v = v.strip()
        if not v:
            return None

        # Basic URL validation
        if not re.match(URL_PATTERN, v):
            raise ValueError(f"Invalid URL format: {v}. Must start with http:// or https://")

        return v

    @field_validator('journal', 'volume', 'pages')
    @classmethod
    def validate_optional_field(cls, v):
        """Validate optional string fields"""
        if v is None:
            return v

        v_stripped = v.strip()
        if not v_stripped:
            return None

        # Check for template injection patterns
        dangerous_patterns = ['{%', '{{', '<%', '${']
        for pattern in dangerous_patterns:
            if pattern in v_stripped:
                raise ValueError(f"Potentially dangerous pattern detected: {pattern}")

        return v_stripped


class CitationGenerateOutput(BaseModel):
    """Type-safe citation generation output"""
    success: bool
    style: Optional[str] = None
    citation: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Production-Grade Citation Tool
# =============================================================================

class CitationGeneratorTool(BaseTool):
    """Production-grade citation generator with validation

    Features:
    - Pydantic validation with size limits
    - Structured logging
    - Template injection protection
    - DOI format validation
    - URL format validation
    - Year range validation
    - Error handling with codes
    - Support for APA, MLA, Chicago, IEEE, BibTeX
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="citation_generate",
                description="Generate academic citations in APA, MLA, Chicago, IEEE, or BibTeX format. Production-grade with validation.",
                category="utilities",
                tags=["citation", "academic", "bibliography"]
            )
        )

    def _execute(
        self,
        title: str,
        authors: str,
        year: int,
        style: str = "apa",
        journal: Optional[str] = None,
        volume: Optional[str] = None,
        pages: Optional[str] = None,
        doi: Optional[str] = None,
        url: Optional[str] = None
    ) -> str:
        """Generate citation

        Args:
            title: Publication title
            authors: Author names (comma-separated)
            year: Publication year (1800-2035)
            style: Citation style - 'apa', 'mla', 'chicago', 'ieee', 'bibtex'
            journal: Journal name (optional)
            volume: Volume number (optional)
            pages: Page range (optional)
            doi: DOI (optional, e.g., 10.1234/example)
            url: URL (optional)

        Returns:
            JSON with CitationGenerateOutput schema
        """
        citation_hash = hashlib.sha256(f"{title}{authors}{year}".encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = CitationGenerateInput(
                title=title,
                authors=authors,
                year=year,
                style=style,
                journal=journal,
                volume=volume,
                pages=pages,
                doi=doi,
                url=url
            )

            logger.info("Generating citation", extra={
                "citation_hash": citation_hash,
                "style": validated.style,
                "year": year
            })

            # Generate citation based on style
            if validated.style == "apa":
                citation = self._format_apa(
                    validated.title,
                    validated.authors,
                    validated.year,
                    validated.journal,
                    validated.volume,
                    validated.pages,
                    validated.doi
                )
            elif validated.style == "mla":
                citation = self._format_mla(
                    validated.title,
                    validated.authors,
                    validated.year,
                    validated.journal,
                    validated.volume,
                    validated.pages,
                    validated.url
                )
            elif validated.style == "chicago":
                citation = self._format_chicago(
                    validated.title,
                    validated.authors,
                    validated.year,
                    validated.journal,
                    validated.volume,
                    validated.pages
                )
            elif validated.style == "ieee":
                citation = self._format_ieee(
                    validated.title,
                    validated.authors,
                    validated.year,
                    validated.journal,
                    validated.volume,
                    validated.pages,
                    validated.doi
                )
            elif validated.style == "bibtex":
                citation = self._format_bibtex(
                    validated.title,
                    validated.authors,
                    validated.year,
                    validated.journal,
                    validated.volume,
                    validated.pages,
                    validated.doi
                )
            else:
                # Should not reach here due to Literal type
                logger.error("Unsupported citation style", extra={
                    "citation_hash": citation_hash,
                    "style": style
                })
                return CitationGenerateOutput(
                    success=False,
                    error=f"Unsupported citation style: {style}",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

            # Build metadata object
            metadata = {
                "title": validated.title,
                "authors": validated.authors,
                "year": validated.year
            }

            if validated.journal:
                metadata["journal"] = validated.journal
            if validated.volume:
                metadata["volume"] = validated.volume
            if validated.pages:
                metadata["pages"] = validated.pages
            if validated.doi:
                metadata["doi"] = validated.doi
            if validated.url:
                metadata["url"] = validated.url

            result = CitationGenerateOutput(
                success=True,
                style=validated.style,
                citation=citation,
                metadata=metadata
            )

            logger.info("Citation generated", extra={
                "citation_hash": citation_hash,
                "style": validated.style,
                "citation_length": len(citation),
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("Citation generation validation failed", extra={"citation_hash": citation_hash}, exc_info=True)
            return CitationGenerateOutput(
                success=False,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except Exception as e:
            logger.error("Citation generation failed", extra={"citation_hash": citation_hash}, exc_info=True)
            return CitationGenerateOutput(
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()

    def _format_apa(
        self,
        title: str,
        authors: str,
        year: int,
        journal: Optional[str],
        volume: Optional[str],
        pages: Optional[str],
        doi: Optional[str]
    ) -> str:
        """Format APA 7th edition citation"""
        author_list = self._parse_authors_apa(authors)
        citation = f"{author_list} ({year}). {title}."

        if journal:
            citation += f" *{journal}*"
            if volume:
                citation += f", *{volume}*"
            if pages:
                citation += f", {pages}"
            citation += "."

        if doi:
            citation += f" https://doi.org/{doi}"

        return citation

    def _format_mla(
        self,
        title: str,
        authors: str,
        year: int,
        journal: Optional[str],
        volume: Optional[str],
        pages: Optional[str],
        url: Optional[str]
    ) -> str:
        """Format MLA 9th edition citation"""
        author_list = self._parse_authors_mla(authors)
        citation = f'{author_list}. "{title}."'

        if journal:
            citation += f" *{journal}*"
            if volume:
                citation += f", vol. {volume}"
            if pages:
                citation += f", {year}, pp. {pages}"
            else:
                citation += f", {year}"
            citation += "."

        if url:
            citation += f" {url}."

        return citation

    def _format_chicago(
        self,
        title: str,
        authors: str,
        year: int,
        journal: Optional[str],
        volume: Optional[str],
        pages: Optional[str]
    ) -> str:
        """Format Chicago 17th edition citation"""
        author_list = self._parse_authors_chicago(authors)
        citation = f'{author_list}. "{title}."'

        if journal:
            citation += f" *{journal}*"
            if volume:
                citation += f" {volume}"
            if pages:
                citation += f" ({year}): {pages}"
            else:
                citation += f" ({year})"
            citation += "."

        return citation

    def _format_ieee(
        self,
        title: str,
        authors: str,
        year: int,
        journal: Optional[str],
        volume: Optional[str],
        pages: Optional[str],
        doi: Optional[str]
    ) -> str:
        """Format IEEE citation"""
        author_list = self._parse_authors_ieee(authors)
        citation = f'{author_list}, "{title},"'

        if journal:
            citation += f" *{journal}*"
            if volume:
                citation += f", vol. {volume}"
            if pages:
                citation += f", pp. {pages}"
            citation += f", {year}."

        if doi:
            citation += f" doi: {doi}"

        return citation

    def _format_bibtex(
        self,
        title: str,
        authors: str,
        year: int,
        journal: Optional[str],
        volume: Optional[str],
        pages: Optional[str],
        doi: Optional[str]
    ) -> str:
        """Format BibTeX citation"""
        # Generate citation key (first author last name + year)
        first_author = authors.split(',')[0].strip()
        # Remove special characters for key
        key = re.sub(r'[^a-zA-Z0-9]', '', first_author.lower()) + str(year)

        lines = [
            f"@article{{{key},",
            f"  title = {{{title}}}",
            f"  author = {{{authors}}}",
            f"  year = {{{year}}}"
        ]

        if journal:
            lines.append(f"  journal = {{{journal}}}")
        if volume:
            lines.append(f"  volume = {{{volume}}}")
        if pages:
            lines.append(f"  pages = {{{pages}}}")
        if doi:
            lines.append(f"  doi = {{{doi}}}")

        lines.append("}")
        return ",\n".join(lines[:-1]) + "\n" + lines[-1]

    def _parse_authors_apa(self, authors: str) -> str:
        """Parse authors for APA format"""
        author_list = [a.strip() for a in authors.split(",")]
        if len(author_list) == 1:
            return author_list[0]
        elif len(author_list) == 2:
            return f"{author_list[0]}, & {author_list[1]}"
        else:
            return f"{', '.join(author_list[:-1])}, & {author_list[-1]}"

    def _parse_authors_mla(self, authors: str) -> str:
        """Parse authors for MLA format"""
        author_list = [a.strip() for a in authors.split(",")]
        if len(author_list) == 1:
            return author_list[0]
        else:
            return f"{author_list[0]}, et al."

    def _parse_authors_chicago(self, authors: str) -> str:
        """Parse authors for Chicago format"""
        return self._parse_authors_apa(authors)

    def _parse_authors_ieee(self, authors: str) -> str:
        """Parse authors for IEEE format"""
        author_list = [a.strip() for a in authors.split(",")]
        if len(author_list) <= 3:
            return " and ".join(author_list)
        else:
            return f"{author_list[0]} et al."
