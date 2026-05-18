"""
Retry with Exponential Backoff for Agent_OS

Handles transient failures with intelligent retry strategies.
Essential for production reliability with unreliable external services.

Features:
- Exponential backoff with jitter
- Configurable max retries
- Retry on specific error types
- Integration with circuit breaker
- Retry metrics tracking

Common Retry Scenarios:
- 429 (Rate Limit): Retry after backoff
- 500/502/503 (Server Error): Temporary issue, retry
- Timeout: Network issue, retry
- Connection Error: Temporary network issue, retry
"""

import time
import random
from typing import Callable, Any, Optional, List, Type
from functools import wraps
from dataclasses import dataclass

from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Retry Configuration
# =============================================================================

@dataclass
class RetryConfig:
    """Retry configuration"""
    max_retries: int = 3
    base_delay: float = 1.0  # Initial delay in seconds
    max_delay: float = 60.0  # Max delay cap
    exponential_base: float = 2.0  # Backoff multiplier
    jitter: bool = True  # Add randomness to prevent thundering herd
    retry_on_exceptions: tuple = (Exception,)  # Exception types to retry


# Default retry config
DEFAULT_RETRY_CONFIG = RetryConfig(
    max_retries=3,
    base_delay=1.0,
    max_delay=60.0,
    exponential_base=2.0,
    jitter=True
)


# Common transient exceptions (should be retried)
TRANSIENT_EXCEPTIONS = (
    "RateLimitError",  # OpenAI rate limit (429)
    "ServiceUnavailableError",  # Service temporarily down (503)
    "InternalServerError",  # Server error (500)
    "BadGatewayError",  # Gateway error (502)
    "GatewayTimeoutError",  # Gateway timeout (504)
    "TimeoutError",  # Request timeout
    "ConnectionError",  # Network connection error
    "APIConnectionError",  # API connection error (OpenAI specific)
    "APITimeoutError",  # API timeout (OpenAI specific)
)


def is_transient_error(exception: Exception) -> bool:
    """
    Check if exception is a transient error that should be retried

    Args:
        exception: Exception to check

    Returns:
        True if transient (should retry), False otherwise
    """
    exception_name = type(exception).__name__

    # Never retry these exceptions (they are final/deterministic)
    NON_RETRYABLE_EXCEPTIONS = (
        "MaxRetriesExceeded",
        "BudgetExceededError",
        "TimeoutError",  # Agent timeout (different from network timeout)
        "AgentTimeoutError",
        "RateLimitExceeded",  # Rate limit should wait, not retry
    )

    if exception_name in NON_RETRYABLE_EXCEPTIONS:
        return False

    # Check against known transient errors
    if exception_name in TRANSIENT_EXCEPTIONS:
        return True

    # Check HTTP status codes in exception message
    error_message = str(exception).lower()
    transient_codes = ["429", "500", "502", "503", "504", "timeout", "connection"]

    return any(code in error_message for code in transient_codes)


class MaxRetriesExceeded(Exception):
    """Raised when max retries exceeded"""
    pass


# =============================================================================
# Exponential Backoff with Jitter
# =============================================================================

def calculate_backoff(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True
) -> float:
    """
    Calculate backoff delay with exponential growth and optional jitter

    Args:
        attempt: Retry attempt number (0-indexed)
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap
        exponential_base: Base for exponential growth (typically 2)
        jitter: Add random jitter to prevent thundering herd

    Returns:
        Delay in seconds

    Algorithm:
        delay = min(base_delay * (exponential_base ^ attempt), max_delay)
        if jitter:
            delay = delay * random(0.5, 1.0)

    Examples:
        Attempt 0: 1s
        Attempt 1: 2s
        Attempt 2: 4s
        Attempt 3: 8s
        Attempt 4: 16s
        With jitter: Each delayed by 50-100% of calculated value
    """
    # Calculate exponential delay
    delay = base_delay * (exponential_base ** attempt)

    # Cap at max delay
    delay = min(delay, max_delay)

    # Add jitter (randomize between 50% and 100% of delay)
    if jitter:
        delay = delay * (0.5 + random.random() * 0.5)

    return delay


# =============================================================================
# Retry Decorator
# =============================================================================

def retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retry_on: Optional[tuple] = None
):
    """
    Decorator to add retry logic with exponential backoff

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap
        exponential_base: Base for exponential growth
        jitter: Add random jitter
        retry_on: Tuple of exception types to retry (None = all)

    Example:
        @retry(max_retries=3, base_delay=1.0)
        def call_api():
            return openai.chat.completions.create(...)

    Raises:
        MaxRetriesExceeded: If all retries exhausted
        Exception: Original exception if not retryable
    """
    if retry_on is None:
        retry_on = (Exception,)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except retry_on as e:
                    last_exception = e

                    # Check if this is a transient error worth retrying
                    if not is_transient_error(e):
                        logger.warning(f"Non-transient error, not retrying: {type(e).__name__}")
                        raise

                    if attempt >= max_retries:
                        logger.error(
                            f"Max retries ({max_retries}) exceeded for {func.__name__}. "
                            f"Last error: {type(e).__name__}: {e}"
                        )
                        raise MaxRetriesExceeded(
                            f"Failed after {max_retries} retries. Last error: {e}"
                        ) from e

                    # Calculate backoff
                    delay = calculate_backoff(
                        attempt=attempt,
                        base_delay=base_delay,
                        max_delay=max_delay,
                        exponential_base=exponential_base,
                        jitter=jitter
                    )

                    logger.warning(
                        f"Retry {attempt + 1}/{max_retries} for {func.__name__} "
                        f"after {type(e).__name__}. Waiting {delay:.2f}s..."
                    )

                    time.sleep(delay)

            # Should never reach here, but just in case
            raise MaxRetriesExceeded(
                f"Failed after {max_retries} retries"
            ) from last_exception

        return wrapper

    return decorator


# =============================================================================
# Retry Handler Class
# =============================================================================

class RetryHandler:
    """
    Retry handler with exponential backoff and metrics

    Features:
    - Configurable retry strategy
    - Metrics tracking
    - Integration with circuit breaker

    Example:
        handler = RetryHandler(config=RetryConfig(max_retries=3))

        result = handler.execute(
            func=call_api,
            args=("query",),
            kwargs={"temperature": 0}
        )
    """

    def __init__(self, config: Optional[RetryConfig] = None):
        """
        Initialize retry handler

        Args:
            config: Retry configuration (uses defaults if None)
        """
        self.config = config or DEFAULT_RETRY_CONFIG

        # Metrics
        self._total_calls = 0
        self._total_retries = 0
        self._total_successes = 0
        self._total_failures = 0
        self._retry_distribution = {}  # Count by retry attempt

        logger.info(
            f"Retry handler initialized: "
            f"max_retries={self.config.max_retries}, "
            f"base_delay={self.config.base_delay}s"
        )

    def execute(
        self,
        func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        Execute function with retry logic

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            MaxRetriesExceeded: If all retries exhausted
            Exception: Original exception if not retryable
        """
        self._total_calls += 1
        last_exception = None

        for attempt in range(self.config.max_retries + 1):
            try:
                result = func(*args, **kwargs)
                self._total_successes += 1

                # Track retry distribution
                if attempt > 0:
                    self._retry_distribution[attempt] = (
                        self._retry_distribution.get(attempt, 0) + 1
                    )

                return result

            except self.config.retry_on_exceptions as e:
                last_exception = e
                self._total_retries += 1

                # Check if transient
                if not is_transient_error(e):
                    logger.warning(f"Non-transient error, not retrying: {type(e).__name__}")
                    self._total_failures += 1
                    raise

                # Max retries exceeded
                if attempt >= self.config.max_retries:
                    logger.error(
                        f"Max retries ({self.config.max_retries}) exceeded. "
                        f"Last error: {type(e).__name__}: {e}"
                    )
                    self._total_failures += 1
                    raise MaxRetriesExceeded(
                        f"Failed after {self.config.max_retries} retries. Last error: {e}"
                    ) from e

                # Calculate backoff
                delay = calculate_backoff(
                    attempt=attempt,
                    base_delay=self.config.base_delay,
                    max_delay=self.config.max_delay,
                    exponential_base=self.config.exponential_base,
                    jitter=self.config.jitter
                )

                logger.warning(
                    f"Retry {attempt + 1}/{self.config.max_retries} "
                    f"after {type(e).__name__}. Waiting {delay:.2f}s..."
                )

                time.sleep(delay)

        # Should never reach here
        self._total_failures += 1
        raise MaxRetriesExceeded(
            f"Failed after {self.config.max_retries} retries"
        ) from last_exception

    def get_metrics(self) -> dict:
        """Get retry metrics"""
        return {
            "total_calls": self._total_calls,
            "total_retries": self._total_retries,
            "total_successes": self._total_successes,
            "total_failures": self._total_failures,
            "success_rate": (
                self._total_successes / self._total_calls
                if self._total_calls > 0 else 0.0
            ),
            "average_retries": (
                self._total_retries / self._total_calls
                if self._total_calls > 0 else 0.0
            ),
            "retry_distribution": self._retry_distribution
        }


# =============================================================================
# Utility Functions
# =============================================================================

def retry_with_backoff(
    func: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True
) -> Any:
    """
    Execute function with retry and exponential backoff

    Args:
        func: Function to execute
        max_retries: Maximum retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap
        exponential_base: Exponential growth base
        jitter: Add random jitter

    Returns:
        Function result

    Raises:
        MaxRetriesExceeded: If all retries exhausted
    """
    handler = RetryHandler(
        config=RetryConfig(
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
            exponential_base=exponential_base,
            jitter=jitter
        )
    )

    return handler.execute(func)
