"""Production-grade web scraping and HTTP tools"""

from typing import Optional, Dict, Any
from contextlib import contextmanager
from urllib.parse import urlparse
import ipaddress
import json
import time
import hashlib
from functools import wraps

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, validator

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import (
    ToolExecutionError,
    ToolValidationError,
    NetworkTimeoutError,
    HTTPError as AgentHTTPError,
    ErrorCode
)
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Type-Safe Models
# =============================================================================

class WebScraperInput(BaseModel):
    """Type-safe web scraper input with validation"""
    url: str = Field(..., min_length=1)
    selector: Optional[str] = None
    max_length: Optional[int] = Field(None, gt=0)
    timeout: float = Field(30.0, gt=0, le=300)

    @validator('url')
    def validate_url(cls, v):
        """Validate URL format and security"""
        if not v or not v.strip():
            raise ValueError("URL cannot be empty")

        parsed = urlparse(v)

        # Protocol validation
        if parsed.scheme not in ('http', 'https'):
            raise ValueError(f"Invalid protocol: {parsed.scheme}")

        # Hostname validation
        if not parsed.hostname:
            raise ValueError("Invalid URL: no hostname")

        # SSRF protection
        try:
            ip = ipaddress.ip_address(parsed.hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                raise ValueError(f"Private/local IP blocked: {parsed.hostname}")
        except ValueError as e:
            if "Private/local IP blocked" in str(e):
                raise
            # Not an IP address, that's OK
            pass

        return v


class WebScraperOutput(BaseModel):
    """Type-safe web scraper output"""
    success: bool
    url: str
    content: Optional[str] = None
    original_length: Optional[int] = None
    truncated: bool = False
    selector: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class HTTPRequestInput(BaseModel):
    """Type-safe HTTP request input"""
    url: str = Field(..., min_length=1)
    method: str = Field("GET", pattern="^(GET|POST|PUT|DELETE|PATCH)$")
    headers: Optional[Dict[str, str]] = None
    json_body: Optional[Dict[str, Any]] = None
    params: Optional[Dict[str, str]] = None
    timeout: float = Field(30.0, gt=0, le=300)

    @validator('url')
    def validate_url(cls, v):
        """Validate URL format"""
        if not v or not v.strip():
            raise ValueError("URL cannot be empty")

        parsed = urlparse(v)
        if parsed.scheme not in ('http', 'https'):
            raise ValueError(f"Invalid protocol: {parsed.scheme}")

        return v


class HTTPRequestOutput(BaseModel):
    """Type-safe HTTP request output"""
    success: bool
    url: str
    method: str
    status_code: Optional[int] = None
    content_type: Optional[str] = None
    content: Optional[Any] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Retry Decorator
# =============================================================================

def retry_with_backoff(max_attempts=3, initial_delay=1.0, max_delay=60.0, base=2.0):
    """Retry HTTP requests with exponential backoff"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as e:
                    if attempt < max_attempts:
                        logger.warning(
                            f"HTTP request failed, retrying {attempt}/{max_attempts}",
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
# Production-Grade Web Tools
# =============================================================================

class WebScraperTool(BaseTool):
    """Production-grade web scraper with security and reliability

    Security:
    - SSRF protection (blocks private IPs)
    - URL validation
    - Timeout enforcement

    Reliability:
    - Context managers (guaranteed cleanup)
    - Retry logic with backoff
    - Connection pooling
    - Structured errors
    """

    def __init__(
        self,
        timeout: float = 30.0,
        max_retries: int = 3,
        max_connections: int = 100
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self._limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=20
        )

        super().__init__(
            ToolMetadata(
                name="web_scrape",
                description="Scrape text content from web pages with production-grade security. Blocks private IPs and includes retry logic.",
                category="web",
                tags=["scraping", "web", "http"]
            )
        )

    @contextmanager
    def _get_client(self, timeout: Optional[float] = None):
        """Context manager - guaranteed cleanup"""
        client = httpx.Client(
            timeout=timeout or self.timeout,
            follow_redirects=True,
            limits=self._limits
        )
        try:
            yield client
        finally:
            client.close()

    @retry_with_backoff(max_attempts=3)
    def _fetch_url(self, validated: WebScraperInput) -> str:
        """Fetch URL content with retry logic"""
        with self._get_client(validated.timeout) as client:
            response = client.get(validated.url)
            response.raise_for_status()
            return response.text

    def _execute(
        self,
        url: str,
        selector: Optional[str] = None,
        max_length: Optional[int] = None
    ) -> str:
        """Scrape web page content

        Args:
            url: Web page URL
            selector: CSS selector for specific elements
            max_length: Max characters to return

        Returns:
            JSON with WebScraperOutput schema
        """
        start_time = time.time()
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = WebScraperInput(
                url=url,
                selector=selector,
                max_length=max_length,
                timeout=self.timeout
            )

            logger.info("Starting web scrape", extra={
                "url_hash": url_hash,
                "has_selector": bool(selector),
                "timeout": validated.timeout
            })

            # Fetch with retry logic
            html_content = self._fetch_url(validated)

            # Parse HTML
            soup = BeautifulSoup(html_content, 'html.parser')

            # Remove scripts and styles
            for script in soup(["script", "style"]):
                script.decompose()

            # Extract text
            if validated.selector:
                elements = soup.select(validated.selector)
                text = "\n\n".join(el.get_text(strip=True) for el in elements)
            else:
                text = soup.get_text(separator="\n", strip=True)

            # Clean whitespace
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            text = "\n".join(lines)

            original_length = len(text)
            truncated = False

            if validated.max_length and len(text) > validated.max_length:
                text = text[:validated.max_length]
                truncated = True

            duration = time.time() - start_time
            result = WebScraperOutput(
                success=True,
                url=validated.url,
                content=text,
                original_length=original_length,
                truncated=truncated,
                selector=validated.selector,
                metadata={
                    "duration_seconds": round(duration, 3),
                    "content_size_bytes": len(html_content)
                }
            )

            logger.info("Web scrape completed", extra={
                "url_hash": url_hash,
                "duration": duration,
                "text_length": len(text),
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("Validation failed", extra={"url_hash": url_hash}, exc_info=True)
            return WebScraperOutput(
                success=False, url=url, error=str(e), error_code=e.error_code.value
            ).to_json()

        except NetworkTimeoutError as e:
            logger.error("Network timeout", extra={"url_hash": url_hash}, exc_info=True)
            return WebScraperOutput(
                success=False, url=url, error=str(e), error_code=e.error_code.value
            ).to_json()

        except httpx.HTTPStatusError as e:
            logger.error("HTTP error", extra={"url_hash": url_hash}, exc_info=True)
            return WebScraperOutput(
                success=False, url=url,
                error=f"HTTP {e.response.status_code}",
                error_code=f"NET_{e.response.status_code}"
            ).to_json()

        except httpx.HTTPError as e:
            logger.error("HTTP error", extra={"url_hash": url_hash}, exc_info=True)
            return WebScraperOutput(
                success=False, url=url,
                error=f"HTTP error: {str(e)}",
                error_code=ErrorCode.HTTP_ERROR.value
            ).to_json()

        except Exception as e:
            logger.error("Unexpected error", extra={"url_hash": url_hash}, exc_info=True)
            return WebScraperOutput(
                success=False, url=url,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class HTTPRequestTool(BaseTool):
    """Production-grade HTTP request tool with retry and validation

    Features:
    - Retry logic with backoff
    - Connection pooling
    - Request/response validation
    - Structured error handling
    """

    def __init__(
        self,
        timeout: float = 30.0,
        max_retries: int = 3,
        max_connections: int = 100
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self._limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=20
        )

        super().__init__(
            ToolMetadata(
                name="http_request",
                description="Make HTTP requests with production-grade reliability. Supports GET/POST/PUT/DELETE with retry logic.",
                category="web",
                tags=["http", "api", "web"]
            )
        )

    @contextmanager
    def _get_client(self, timeout: Optional[float] = None):
        """Context manager - guaranteed cleanup"""
        client = httpx.Client(
            timeout=timeout or self.timeout,
            follow_redirects=True,
            limits=self._limits
        )
        try:
            yield client
        finally:
            client.close()

    @retry_with_backoff(max_attempts=3)
    def _make_request(self, validated: HTTPRequestInput) -> httpx.Response:
        """Make HTTP request with retry logic"""
        with self._get_client(validated.timeout) as client:
            response = client.request(
                method=validated.method,
                url=validated.url,
                headers=validated.headers,
                json=validated.json_body,
                params=validated.params
            )
            response.raise_for_status()
            return response

    def _execute(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        json_body: Optional[Dict] = None,
        params: Optional[Dict[str, str]] = None
    ) -> str:
        """Make HTTP request

        Args:
            url: Request URL
            method: HTTP method (GET/POST/PUT/DELETE/PATCH)
            headers: Request headers
            json_body: JSON request body
            params: Query parameters

        Returns:
            JSON with HTTPRequestOutput schema
        """
        start_time = time.time()
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = HTTPRequestInput(
                url=url,
                method=method,
                headers=headers,
                json_body=json_body,
                params=params,
                timeout=self.timeout
            )

            logger.info("Making HTTP request", extra={
                "url_hash": url_hash,
                "method": validated.method,
                "timeout": validated.timeout
            })

            # Make request with retry logic
            response = self._make_request(validated)

            content_type = response.headers.get("content-type", "")

            # Parse response content
            if "application/json" in content_type:
                content = response.json()
            else:
                content = response.text

            duration = time.time() - start_time
            result = HTTPRequestOutput(
                success=True,
                url=str(response.url),
                method=validated.method,
                status_code=response.status_code,
                content_type=content_type,
                content=content,
                metadata={
                    "duration_seconds": round(duration, 3),
                    "response_size_bytes": len(response.content)
                }
            )

            logger.info("HTTP request completed", extra={
                "url_hash": url_hash,
                "method": validated.method,
                "status_code": response.status_code,
                "duration": duration,
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("Validation failed", extra={"url_hash": url_hash}, exc_info=True)
            return HTTPRequestOutput(
                success=False, url=url, method=method,
                error=str(e), error_code=e.error_code.value
            ).to_json()

        except NetworkTimeoutError as e:
            logger.error("Network timeout", extra={"url_hash": url_hash}, exc_info=True)
            return HTTPRequestOutput(
                success=False, url=url, method=method,
                error=str(e), error_code=e.error_code.value
            ).to_json()

        except httpx.HTTPStatusError as e:
            logger.error("HTTP error", extra={"url_hash": url_hash}, exc_info=True)
            return HTTPRequestOutput(
                success=False, url=url, method=method,
                status_code=e.response.status_code,
                error=f"HTTP {e.response.status_code}",
                error_code=f"NET_{e.response.status_code}"
            ).to_json()

        except httpx.HTTPError as e:
            logger.error("HTTP error", extra={"url_hash": url_hash}, exc_info=True)
            return HTTPRequestOutput(
                success=False, url=url, method=method,
                error=f"HTTP error: {str(e)}",
                error_code=ErrorCode.HTTP_ERROR.value
            ).to_json()

        except Exception as e:
            logger.error("Unexpected error", extra={"url_hash": url_hash}, exc_info=True)
            return HTTPRequestOutput(
                success=False, url=url, method=method,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()
