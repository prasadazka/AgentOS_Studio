"""Production-grade ArXiv academic paper search tools"""

import hashlib
from typing import Optional, List, Literal
from datetime import datetime

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

class ArxivSearchInput(BaseModel):
    """Type-safe ArXiv search input with validation"""
    query: str = Field(..., min_length=1, max_length=500)
    max_results: int = Field(5, ge=1, le=100)
    sort_by: Literal["relevance", "submitted", "updated"] = "relevance"

    @validator('query')
    def validate_query(cls, v):
        """Validate query content"""
        if not v or not v.strip():
            raise ValueError("Query cannot be empty")
        return v.strip()


class ArxivPaper(BaseModel):
    """Type-safe ArXiv paper representation"""
    title: str
    authors: List[str]
    published: str
    updated: str
    categories: List[str]
    abstract: str
    pdf_url: str
    arxiv_id: str


class ArxivSearchOutput(BaseModel):
    """Type-safe ArXiv search output"""
    success: bool
    query: str = ""
    total_results: int = 0
    papers: List[ArxivPaper] = Field(default_factory=list)
    message: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class ArxivPaperInput(BaseModel):
    """Type-safe ArXiv paper input with validation"""
    arxiv_id: str = Field(..., min_length=1, max_length=50)

    @validator('arxiv_id')
    def validate_arxiv_id(cls, v):
        """Validate ArXiv ID format"""
        if not v or not v.strip():
            raise ValueError("ArXiv ID cannot be empty")

        # Basic ArXiv ID format validation (e.g., 2301.00001 or 1234.5678v2)
        import re
        pattern = r'^\d{4}\.\d{4,5}(v\d+)?$'
        if not re.match(pattern, v.strip()):
            raise ValueError(
                f"Invalid ArXiv ID format: {v}. "
                f"Expected format: YYMM.NNNNN (e.g., 2301.00001)"
            )

        return v.strip()


class ArxivPaperOutput(BaseModel):
    """Type-safe ArXiv paper output"""
    success: bool
    title: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    published: Optional[str] = None
    updated: Optional[str] = None
    categories: List[str] = Field(default_factory=list)
    arxiv_id: str = ""
    abstract: Optional[str] = None
    pdf_url: Optional[str] = None
    doi: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Production-Grade ArXiv Tools
# =============================================================================

class ArxivSearchTool(BaseTool):
    """Production-grade ArXiv search with validation

    Features:
    - Pydantic validation with size limits
    - Structured logging
    - Error handling with codes
    - Sort criterion validation
    - Query sanitization
    """

    def __init__(self):
        self._client = None  # Lazy initialization

        super().__init__(
            ToolMetadata(
                name="arxiv_search",
                description="Search ArXiv for academic papers. Production-grade with validation.",
                category="research",
                tags=["academic", "papers", "research", "science"]
            )
        )

    @property
    def client(self):
        """Lazy initialization of ArXiv client"""
        if self._client is None:
            try:
                import arxiv
                self._client = arxiv.Client()
            except ImportError:
                raise ToolExecutionError(
                    "arxiv not installed. Install with: pip install arxiv",
                    details={"missing_package": "arxiv"}
                )
        return self._client

    def _execute(
        self,
        query: str,
        max_results: int = 5,
        sort_by: str = "relevance"
    ) -> str:
        """Search ArXiv papers

        Args:
            query: Search query (can use ArXiv syntax like 'ti:quantum')
            max_results: Number of results (default: 5, max: 100)
            sort_by: Sort order - 'relevance', 'submitted', 'updated'

        Returns:
            JSON with ArxivSearchOutput schema
        """
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = ArxivSearchInput(
                query=query,
                max_results=max_results,
                sort_by=sort_by
            )

            logger.info("Searching ArXiv", extra={
                "query_hash": query_hash,
                "max_results": max_results,
                "sort_by": sort_by
            })

            # Import arxiv here after validation
            import arxiv

            # Map sort criterion
            sort_criterion = {
                "relevance": arxiv.SortCriterion.Relevance,
                "submitted": arxiv.SortCriterion.SubmittedDate,
                "updated": arxiv.SortCriterion.LastUpdatedDate
            }[validated.sort_by]

            # Execute search
            search = arxiv.Search(
                query=validated.query,
                max_results=validated.max_results,
                sort_by=sort_criterion
            )

            results = list(self.client.results(search))

            if not results:
                logger.info("No ArXiv papers found", extra={
                    "query_hash": query_hash,
                    "query": validated.query
                })
                return ArxivSearchOutput(
                    success=True,
                    query=validated.query,
                    total_results=0,
                    papers=[],
                    message=f"No papers found for query: {validated.query}"
                ).to_json()

            # Build structured paper data
            papers_data = []
            for paper in results:
                papers_data.append(ArxivPaper(
                    title=paper.title,
                    authors=[a.name for a in paper.authors],
                    published=paper.published.strftime("%Y-%m-%d"),
                    updated=paper.updated.strftime("%Y-%m-%d"),
                    categories=paper.categories,
                    abstract=paper.summary,
                    pdf_url=paper.pdf_url,
                    arxiv_id=paper.entry_id.split("/")[-1]
                ))

            result = ArxivSearchOutput(
                success=True,
                query=validated.query,
                total_results=len(results),
                papers=papers_data
            )

            logger.info("ArXiv search completed", extra={
                "query_hash": query_hash,
                "results_count": len(results),
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("ArXiv search validation failed", extra={"query_hash": query_hash}, exc_info=True)
            return ArxivSearchOutput(
                success=False,
                query=query,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except ImportError:
            logger.error("arxiv not installed", extra={"query_hash": query_hash})
            return ArxivSearchOutput(
                success=False,
                query=query,
                error="arxiv not installed. Install with: pip install arxiv",
                error_code=ErrorCode.TOOL_DEPENDENCY_MISSING.value
            ).to_json()

        except Exception as e:
            logger.error("ArXiv search failed", extra={"query_hash": query_hash}, exc_info=True)
            return ArxivSearchOutput(
                success=False,
                query=query,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class ArxivPaperTool(BaseTool):
    """Production-grade ArXiv paper retrieval with validation

    Features:
    - Pydantic validation with ArXiv ID format check
    - Structured logging
    - Error handling with codes
    - ID sanitization
    """

    def __init__(self):
        self._client = None  # Lazy initialization

        super().__init__(
            ToolMetadata(
                name="arxiv_paper",
                description="Get detailed ArXiv paper info by ID. Production-grade with ID validation.",
                category="research",
                tags=["academic", "papers", "details"]
            )
        )

    @property
    def client(self):
        """Lazy initialization of ArXiv client"""
        if self._client is None:
            try:
                import arxiv
                self._client = arxiv.Client()
            except ImportError:
                raise ToolExecutionError(
                    "arxiv not installed. Install with: pip install arxiv",
                    details={"missing_package": "arxiv"}
                )
        return self._client

    def _execute(self, arxiv_id: str) -> str:
        """Get paper details by ArXiv ID

        Args:
            arxiv_id: ArXiv paper ID (e.g., '2301.00001')

        Returns:
            JSON with ArxivPaperOutput schema
        """
        id_hash = hashlib.sha256(arxiv_id.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = ArxivPaperInput(arxiv_id=arxiv_id)

            logger.info("Retrieving ArXiv paper", extra={
                "id_hash": id_hash,
                "arxiv_id": validated.arxiv_id
            })

            # Import arxiv here after validation
            import arxiv

            # Execute search by ID
            search = arxiv.Search(id_list=[validated.arxiv_id])

            try:
                paper = next(self.client.results(search))
            except StopIteration:
                logger.info("ArXiv paper not found", extra={
                    "id_hash": id_hash,
                    "arxiv_id": validated.arxiv_id
                })
                return ArxivPaperOutput(
                    success=False,
                    arxiv_id=validated.arxiv_id,
                    error=f"Paper with ID '{validated.arxiv_id}' not found",
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                ).to_json()

            # Build structured paper data
            result = ArxivPaperOutput(
                success=True,
                title=paper.title,
                authors=[a.name for a in paper.authors],
                published=paper.published.strftime('%Y-%m-%d'),
                updated=paper.updated.strftime('%Y-%m-%d'),
                categories=paper.categories,
                arxiv_id=validated.arxiv_id,
                abstract=paper.summary,
                pdf_url=paper.pdf_url,
                doi=paper.doi if paper.doi else None
            )

            logger.info("ArXiv paper retrieved", extra={
                "id_hash": id_hash,
                "title": paper.title,
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("ArXiv paper validation failed", extra={"id_hash": id_hash}, exc_info=True)
            return ArxivPaperOutput(
                success=False,
                arxiv_id=arxiv_id,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except ImportError:
            logger.error("arxiv not installed", extra={"id_hash": id_hash})
            return ArxivPaperOutput(
                success=False,
                arxiv_id=arxiv_id,
                error="arxiv not installed. Install with: pip install arxiv",
                error_code=ErrorCode.TOOL_DEPENDENCY_MISSING.value
            ).to_json()

        except Exception as e:
            logger.error("ArXiv paper retrieval failed", extra={"id_hash": id_hash}, exc_info=True)
            return ArxivPaperOutput(
                success=False,
                arxiv_id=arxiv_id,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()
