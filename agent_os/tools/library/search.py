"""Production-grade web search tools with retry logic and rate limiting"""

import os
import json
import time
import hashlib
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from functools import wraps

import httpx
from pydantic import BaseModel, Field, validator

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import (
    ToolExecutionError,
    ToolValidationError,
    NetworkTimeoutError,
    HTTPError,
    ErrorCode
)
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Type-Safe Models
# =============================================================================

class SearchInput(BaseModel):
    """Type-safe search input with validation"""
    query: str = Field(..., min_length=1, max_length=500)
    max_results: int = Field(5, gt=0, le=20)

    @validator('query')
    def validate_query(cls, v):
        if not v or not v.strip():
            raise ValueError("Query cannot be empty")
        # Remove excessive whitespace
        return ' '.join(v.split())


class TavilySearchInput(SearchInput):
    """Type-safe Tavily search input"""
    search_depth: str = Field("basic", pattern="^(basic|advanced)$")
    include_domains: Optional[List[str]] = None
    exclude_domains: Optional[List[str]] = None


class SearchOutput(BaseModel):
    """Type-safe search output"""
    success: bool
    query: str
    backend: str
    answer: Optional[str] = None
    results: List[Dict[str, Any]] = Field(default_factory=list)
    total_results: int = 0
    error: Optional[str] = None
    error_code: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Retry Decorator with Rate Limiting
# =============================================================================

def retry_with_backoff(max_attempts=3, initial_delay=1.0, max_delay=60.0, base=2.0):
    """Retry with exponential backoff and rate limit handling"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except httpx.HTTPStatusError as e:
                    # Don't retry on 401 (auth error) or 400 (bad request)
                    if e.response.status_code in [400, 401, 403]:
                        raise

                    # Retry on 429 (rate limit) and 5xx errors
                    if attempt < max_attempts:
                        # Respect Retry-After header if present
                        retry_after = e.response.headers.get('Retry-After')
                        if retry_after:
                            try:
                                delay = float(retry_after)
                            except ValueError:
                                pass

                        logger.warning(
                            f"Search failed (HTTP {e.response.status_code}), retrying {attempt}/{max_attempts}",
                            extra={"attempt": attempt, "delay": delay, "status": e.response.status_code}
                        )
                        time.sleep(delay)
                        delay = min(delay * base, max_delay)
                    else:
                        raise
                except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as e:
                    if attempt < max_attempts:
                        logger.warning(
                            f"Network error, retrying {attempt}/{max_attempts}",
                            extra={"attempt": attempt, "delay": delay}
                        )
                        time.sleep(delay)
                        delay = min(delay * base, max_delay)
                    else:
                        raise NetworkTimeoutError(
                            f"Failed after {max_attempts} attempts",
                            details={"last_error": str(e)}
                        ) from e
            raise
        return wrapper
    return decorator


# =============================================================================
# Production-Grade Search Tools
# =============================================================================

class TavilySearchTool(BaseTool):
    """Production-grade Tavily search with retry logic and validation

    Features:
    - Retry logic with exponential backoff
    - Rate limit handling with Retry-After
    - API key validation
    - Timeout enforcement
    - Structured error codes
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        search_depth: str = "basic",
        max_results: int = 5,
        include_answer: bool = True,
        include_raw_content: bool = False,
        timeout: float = 30.0,
        max_retries: int = 3
    ):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")
        if not self.api_key or not self.api_key.strip():
            raise ToolValidationError(
                "Tavily API key required. Set TAVILY_API_KEY env var or pass api_key parameter. Get one at https://tavily.com",
                field_name="api_key"
            )

        self.search_depth = search_depth
        self.max_results = max_results
        self.include_answer = include_answer
        self.include_raw_content = include_raw_content
        self.timeout = timeout
        self.max_retries = max_retries
        self.api_url = "https://api.tavily.com/search"

        super().__init__(
            ToolMetadata(
                name="tavily_search",
                description="Search the web using Tavily API with production-grade retry logic and rate limiting.",
                category="search",
                tags=["search", "web", "tavily", "rag"]
            )
        )

    @contextmanager
    def _get_client(self):
        """Context manager - guaranteed cleanup"""
        client = httpx.Client(timeout=self.timeout)
        try:
            yield client
        finally:
            client.close()

    @retry_with_backoff(max_attempts=3)
    def _make_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Make API request with retry logic"""
        with self._get_client() as client:
            response = client.post(self.api_url, json=payload)
            response.raise_for_status()
            return response.json()

    def _execute(
        self,
        query: str,
        search_depth: Optional[str] = None,
        max_results: Optional[int] = None,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None
    ) -> str:
        """Search the web using Tavily API

        Args:
            query: Search query (max 500 chars)
            search_depth: "basic" or "advanced"
            max_results: Number of results (1-20)
            include_domains: Only search these domains
            exclude_domains: Exclude these domains

        Returns:
            JSON with SearchOutput schema
        """
        start_time = time.time()
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = TavilySearchInput(
                query=query,
                max_results=max_results or self.max_results,
                search_depth=search_depth or self.search_depth,
                include_domains=include_domains,
                exclude_domains=exclude_domains
            )

            logger.info("Executing Tavily search", extra={
                "query_hash": query_hash,
                "search_depth": validated.search_depth,
                "max_results": validated.max_results
            })

            # Build payload
            payload = {
                "api_key": self.api_key,
                "query": validated.query,
                "search_depth": validated.search_depth,
                "max_results": validated.max_results,
                "include_answer": self.include_answer,
                "include_raw_content": self.include_raw_content
            }

            if validated.include_domains:
                payload["include_domains"] = validated.include_domains
            if validated.exclude_domains:
                payload["exclude_domains"] = validated.exclude_domains

            # Make request with retry
            data = self._make_request(payload)

            # Format results
            results = []
            for result in data.get("results", []):
                results.append({
                    "title": result.get("title"),
                    "url": result.get("url"),
                    "content": result.get("content"),
                    "score": result.get("score"),
                    "published_date": result.get("published_date")
                })

            duration = time.time() - start_time
            output = SearchOutput(
                success=True,
                query=validated.query,
                backend="tavily",
                answer=data.get("answer"),
                results=results,
                total_results=len(results),
                metadata={
                    "duration_seconds": round(duration, 3),
                    "search_depth": validated.search_depth
                }
            )

            logger.info("Tavily search completed", extra={
                "query_hash": query_hash,
                "duration": duration,
                "results_count": len(results)
            })

            return output.to_json()

        except ToolValidationError as e:
            logger.error("Validation failed", extra={"query_hash": query_hash}, exc_info=True)
            return SearchOutput(
                success=False,
                query=query,
                backend="tavily",
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except httpx.HTTPStatusError as e:
            logger.error("Tavily API error", extra={
                "query_hash": query_hash,
                "status_code": e.response.status_code
            }, exc_info=True)

            if e.response.status_code == 401:
                error = "Invalid Tavily API key"
                error_code = ErrorCode.HTTP_401.value
            elif e.response.status_code == 429:
                error = "Rate limit exceeded. Upgrade plan or wait."
                error_code = ErrorCode.HTTP_429.value
            else:
                error = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
                error_code = f"NET_{e.response.status_code}"

            return SearchOutput(
                success=False,
                query=query,
                backend="tavily",
                error=error,
                error_code=error_code
            ).to_json()

        except NetworkTimeoutError as e:
            logger.error("Network timeout", extra={"query_hash": query_hash}, exc_info=True)
            return SearchOutput(
                success=False,
                query=query,
                backend="tavily",
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except Exception as e:
            logger.error("Unexpected error", extra={"query_hash": query_hash}, exc_info=True)
            return SearchOutput(
                success=False,
                query=query,
                backend="tavily",
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class DuckDuckGoSearchTool(BaseTool):
    """Production-grade DuckDuckGo search with retry logic

    Features:
    - Retry logic for transient failures
    - Timeout enforcement
    - Structured error handling
    - Free, no API key required
    """

    def __init__(self, max_results: int = 5, timeout: float = 30.0, max_retries: int = 3):
        self.max_results = max_results
        self.timeout = timeout
        self.max_retries = max_retries

        super().__init__(
            ToolMetadata(
                name="duckduckgo_search",
                description="Search the web using DuckDuckGo with retry logic. Free, no API key required.",
                category="search",
                tags=["search", "web", "duckduckgo", "free"]
            )
        )

    @retry_with_backoff(max_attempts=3)
    def _perform_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Perform search with retry logic"""
        from ddgs import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))

        return results

    def _execute(self, query: str, max_results: Optional[int] = None) -> str:
        """Search using DuckDuckGo

        Args:
            query: Search query (max 500 chars)
            max_results: Number of results (1-20)

        Returns:
            JSON with SearchOutput schema
        """
        start_time = time.time()
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = SearchInput(
                query=query,
                max_results=max_results or self.max_results
            )

            logger.info("Executing DuckDuckGo search", extra={
                "query_hash": query_hash,
                "max_results": validated.max_results
            })

            # Perform search with retry
            raw_results = self._perform_search(validated.query, validated.max_results)

            # Format results
            results = []
            for result in raw_results:
                results.append({
                    "title": result.get("title"),
                    "url": result.get("href"),
                    "content": result.get("body")
                })

            duration = time.time() - start_time
            output = SearchOutput(
                success=True,
                query=validated.query,
                backend="duckduckgo",
                results=results,
                total_results=len(results),
                metadata={"duration_seconds": round(duration, 3)}
            )

            logger.info("DuckDuckGo search completed", extra={
                "query_hash": query_hash,
                "duration": duration,
                "results_count": len(results)
            })

            return output.to_json()

        except ImportError:
            logger.error("ddgs not installed", extra={"query_hash": query_hash})
            return SearchOutput(
                success=False,
                query=query,
                backend="duckduckgo",
                error="ddgs not installed. Install with: pip install ddgs",
                error_code=ErrorCode.TOOL_DEPENDENCY_MISSING.value
            ).to_json()

        except ToolValidationError as e:
            logger.error("Validation failed", extra={"query_hash": query_hash}, exc_info=True)
            return SearchOutput(
                success=False,
                query=query,
                backend="duckduckgo",
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except Exception as e:
            logger.error("Unexpected error", extra={"query_hash": query_hash}, exc_info=True)
            return SearchOutput(
                success=False,
                query=query,
                backend="duckduckgo",
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class WebSearchTool(BaseTool):
    """Production-grade unified web search with automatic backend selection

    Features:
    - Automatic backend selection (Tavily → DuckDuckGo)
    - Fallback on failure
    - Consistent interface
    - All production patterns from individual tools
    """

    def __init__(
        self,
        backend: Optional[str] = None,
        auto_fallback: bool = True,
        **backend_kwargs
    ):
        """Initialize unified web search

        Args:
            backend: Force "tavily" or "duckduckgo" (None = auto-select)
            auto_fallback: Fallback to alternative if primary fails
            **backend_kwargs: Backend-specific arguments
        """
        self.backend = backend
        self.auto_fallback = auto_fallback
        self.backend_kwargs = backend_kwargs
        self._adapter = None
        self._selected_backend = None

        self._initialize_backend()

        super().__init__(
            ToolMetadata(
                name="web_search",
                description=f"Search the web with automatic backend selection and fallback. Using: {self._selected_backend}",
                category="search",
                tags=["search", "web", "internet", self._selected_backend]
            )
        )

    def _initialize_backend(self):
        """Initialize search backend with fallback logic"""
        if self.backend == "duckduckgo":
            self._adapter = DuckDuckGoSearchTool(**self.backend_kwargs)
            self._selected_backend = "duckduckgo"

        elif self.backend == "tavily":
            try:
                self._adapter = TavilySearchTool(**self.backend_kwargs)
                self._selected_backend = "tavily"
            except ToolValidationError as e:
                if self.auto_fallback:
                    logger.warning("Tavily unavailable, falling back to DuckDuckGo", extra={
                        "reason": str(e)
                    })
                    self._adapter = DuckDuckGoSearchTool(**self.backend_kwargs)
                    self._selected_backend = "duckduckgo"
                else:
                    raise

        else:
            # Auto-select: Tavily → DuckDuckGo
            try:
                self._adapter = TavilySearchTool(**self.backend_kwargs)
                self._selected_backend = "tavily"
            except ToolValidationError:
                self._adapter = DuckDuckGoSearchTool(**self.backend_kwargs)
                self._selected_backend = "duckduckgo"

    def _execute(self, query: str, **kwargs) -> str:
        """Execute web search

        Args:
            query: Search query
            **kwargs: Backend-specific parameters

        Returns:
            JSON with SearchOutput schema
        """
        return self._adapter._execute(query, **kwargs)
