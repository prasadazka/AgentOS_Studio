"""Production-grade Wikipedia search and content retrieval tools"""

import hashlib
from typing import Optional, List
from pydantic import BaseModel, Field, validator

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import (
    ToolExecutionError,
    ToolValidationError,
    ErrorCode
)
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Type-Safe Models
# =============================================================================

class WikipediaSearchInput(BaseModel):
    """Type-safe Wikipedia search input with validation"""
    query: str = Field(..., min_length=1, max_length=300)
    sentences: int = Field(3, ge=1, le=20)

    @validator('query')
    def validate_query(cls, v):
        """Validate query content"""
        if not v or not v.strip():
            raise ValueError("Query cannot be empty")
        return v.strip()


class WikipediaSearchOutput(BaseModel):
    """Type-safe Wikipedia search output"""
    success: bool
    found: bool = False
    title: Optional[str] = None
    summary: Optional[str] = None
    url: Optional[str] = None
    query: str = ""
    suggestions: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class WikipediaContentInput(BaseModel):
    """Type-safe Wikipedia content input with validation"""
    title: str = Field(..., min_length=1, max_length=300)
    max_chars: Optional[int] = Field(None, gt=0, le=1000000)  # 1MB max

    @validator('title')
    def validate_title(cls, v):
        """Validate title content"""
        if not v or not v.strip():
            raise ValueError("Title cannot be empty")
        return v.strip()


class WikipediaContentOutput(BaseModel):
    """Type-safe Wikipedia content output"""
    success: bool
    title: Optional[str] = None
    content: Optional[str] = None
    url: Optional[str] = None
    truncated: bool = False
    content_length: int = 0
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Production-Grade Wikipedia Tools
# =============================================================================

class WikipediaSearchTool(BaseTool):
    """Production-grade Wikipedia search with validation

    Features:
    - Pydantic validation with size limits
    - Structured logging
    - Error handling with codes
    - Search suggestions on failure
    - Query sanitization
    """

    def __init__(self, language: str = "en", user_agent: str = "AgentOS/1.0"):
        self.language = language
        self.user_agent = user_agent
        self._wiki = None  # Lazy initialization

        super().__init__(
            ToolMetadata(
                name="wikipedia_search",
                description="Search Wikipedia with production-grade validation. Returns article summaries.",
                category="research",
                tags=["search", "encyclopedia", "facts", "research"]
            )
        )

    @property
    def wiki(self):
        """Lazy initialization of Wikipedia client"""
        if self._wiki is None:
            try:
                from wikipediaapi import Wikipedia
                self._wiki = Wikipedia(
                    language=self.language,
                    user_agent=self.user_agent
                )
            except ImportError:
                raise ToolExecutionError(
                    "Wikipedia-API not installed. Install with: pip install wikipedia-api",
                    details={"missing_package": "wikipedia-api"}
                )
        return self._wiki

    def _execute(self, query: str, sentences: int = 3) -> str:
        """Search Wikipedia and return summary

        Args:
            query: Search term
            sentences: Number of sentences to return (default: 3, max: 20)

        Returns:
            JSON with WikipediaSearchOutput schema
        """
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = WikipediaSearchInput(
                query=query,
                sentences=sentences
            )

            logger.info("Searching Wikipedia", extra={
                "query_hash": query_hash,
                "language": self.language,
                "sentences": sentences
            })

            # Search Wikipedia
            page = self.wiki.page(validated.query)

            if not page.exists():
                logger.info("Wikipedia article not found", extra={
                    "query_hash": query_hash,
                    "query": validated.query
                })

                suggestions = self._get_suggestions(validated.query)
                return WikipediaSearchOutput(
                    success=True,
                    found=False,
                    query=validated.query,
                    suggestions=suggestions[:5] if suggestions else []
                ).to_json()

            # Extract summary (approximate by character count)
            # Rough estimate: ~150 chars per sentence
            summary_length = validated.sentences * 150
            summary = page.summary[:summary_length] if summary_length else page.summary

            result = WikipediaSearchOutput(
                success=True,
                found=True,
                title=page.title,
                summary=summary,
                url=page.fullurl,
                query=validated.query
            )

            logger.info("Wikipedia search completed", extra={
                "query_hash": query_hash,
                "found": True,
                "title": page.title,
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("Wikipedia search validation failed", extra={"query_hash": query_hash}, exc_info=True)
            return WikipediaSearchOutput(
                success=False,
                found=False,
                query=query,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except ImportError as e:
            logger.error("Wikipedia-API not installed", extra={"query_hash": query_hash})
            return WikipediaSearchOutput(
                success=False,
                found=False,
                query=query,
                error="Wikipedia-API not installed. Install with: pip install wikipedia-api",
                error_code=ErrorCode.TOOL_DEPENDENCY_MISSING.value
            ).to_json()

        except Exception as e:
            logger.error("Wikipedia search failed", extra={"query_hash": query_hash}, exc_info=True)
            return WikipediaSearchOutput(
                success=False,
                found=False,
                query=query,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()

    def _get_suggestions(self, query: str) -> List[str]:
        """Get search suggestions for failed query"""
        try:
            # Wikipedia-API doesn't provide direct search suggestions
            # Return empty list (future: could integrate with MediaWiki API)
            return []
        except Exception:
            return []


class WikipediaContentTool(BaseTool):
    """Production-grade Wikipedia content retrieval with validation

    Features:
    - Pydantic validation with size limits
    - Content truncation with max_chars limit
    - Structured logging
    - Error handling with codes
    - Title sanitization
    """

    def __init__(self, language: str = "en", user_agent: str = "AgentOS/1.0"):
        self.language = language
        self.user_agent = user_agent
        self._wiki = None  # Lazy initialization

        super().__init__(
            ToolMetadata(
                name="wikipedia_content",
                description="Retrieve full Wikipedia article content. Production-grade with size limits.",
                category="research",
                tags=["content", "encyclopedia", "research"]
            )
        )

    @property
    def wiki(self):
        """Lazy initialization of Wikipedia client"""
        if self._wiki is None:
            try:
                from wikipediaapi import Wikipedia
                self._wiki = Wikipedia(
                    language=self.language,
                    user_agent=self.user_agent
                )
            except ImportError:
                raise ToolExecutionError(
                    "Wikipedia-API not installed. Install with: pip install wikipedia-api",
                    details={"missing_package": "wikipedia-api"}
                )
        return self._wiki

    def _execute(self, title: str, max_chars: Optional[int] = None) -> str:
        """Get full article content

        Args:
            title: Article title
            max_chars: Maximum characters to return (default: unlimited, max: 1MB)

        Returns:
            JSON with WikipediaContentOutput schema
        """
        title_hash = hashlib.sha256(title.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = WikipediaContentInput(
                title=title,
                max_chars=max_chars
            )

            logger.info("Retrieving Wikipedia content", extra={
                "title_hash": title_hash,
                "language": self.language,
                "max_chars": max_chars
            })

            # Get article
            page = self.wiki.page(validated.title)

            if not page.exists():
                logger.info("Wikipedia article not found", extra={
                    "title_hash": title_hash,
                    "title": validated.title
                })
                return WikipediaContentOutput(
                    success=False,
                    error=f"Article '{validated.title}' not found",
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                ).to_json()

            # Extract content
            content = page.text
            truncated = False

            if validated.max_chars and len(content) > validated.max_chars:
                content = content[:validated.max_chars]
                truncated = True

            result = WikipediaContentOutput(
                success=True,
                title=page.title,
                content=content,
                url=page.fullurl,
                truncated=truncated,
                content_length=len(content)
            )

            logger.info("Wikipedia content retrieved", extra={
                "title_hash": title_hash,
                "content_length": len(content),
                "truncated": truncated,
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("Wikipedia content validation failed", extra={"title_hash": title_hash}, exc_info=True)
            return WikipediaContentOutput(
                success=False,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except ImportError as e:
            logger.error("Wikipedia-API not installed", extra={"title_hash": title_hash})
            return WikipediaContentOutput(
                success=False,
                error="Wikipedia-API not installed. Install with: pip install wikipedia-api",
                error_code=ErrorCode.TOOL_DEPENDENCY_MISSING.value
            ).to_json()

        except Exception as e:
            logger.error("Wikipedia content retrieval failed", extra={"title_hash": title_hash}, exc_info=True)
            return WikipediaContentOutput(
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()
