"""
Rate Limiting for Agent_OS

Implements token bucket algorithm to prevent exceeding API rate limits.
Essential for production deployments with multiple agents and high throughput.

Features:
- Token bucket algorithm for smooth rate limiting
- Per-model rate limits (TPM, RPM)
- Automatic throttling with exponential backoff
- Thread-safe implementation
- Rate limit metrics and monitoring

Common API Rate Limits (as of January 2025):
- OpenAI GPT-4o: 10,000 TPM, 500 RPM (Tier 1)
- OpenAI GPT-4o-mini: 200,000 TPM, 500 RPM (Tier 1)
- Anthropic Claude: 400,000 TPM, 1,000 RPM (Tier 1)
- Google Gemini: 1,000,000 TPM, 1,500 RPM (Free tier)
"""

import time
from typing import Dict, Optional, Any
from dataclasses import dataclass
from threading import RLock
from datetime import datetime

from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Rate Limit Configuration
# =============================================================================

@dataclass
class RateLimitConfig:
    """Rate limit configuration"""
    tokens_per_minute: int  # TPM limit
    requests_per_minute: int  # RPM limit
    burst_size: Optional[int] = None  # Max burst tokens (defaults to TPM)

    def __post_init__(self):
        if self.burst_size is None:
            # Allow short bursts up to TPM
            self.burst_size = self.tokens_per_minute


# Per-model rate limits (default OpenAI Tier 1)
MODEL_RATE_LIMITS = {
    # OpenAI Models (Tier 1 limits)
    "gpt-4o": RateLimitConfig(tokens_per_minute=10_000, requests_per_minute=500),
    "gpt-4o-mini": RateLimitConfig(tokens_per_minute=200_000, requests_per_minute=500),
    "gpt-4-turbo": RateLimitConfig(tokens_per_minute=10_000, requests_per_minute=500),
    "gpt-4": RateLimitConfig(tokens_per_minute=10_000, requests_per_minute=500),
    "gpt-3.5-turbo": RateLimitConfig(tokens_per_minute=60_000, requests_per_minute=500),

    # Anthropic Models (Tier 1 limits)
    "claude-3-opus-20240229": RateLimitConfig(tokens_per_minute=400_000, requests_per_minute=1_000),
    "claude-3-sonnet-20240229": RateLimitConfig(tokens_per_minute=400_000, requests_per_minute=1_000),
    "claude-3-haiku-20240307": RateLimitConfig(tokens_per_minute=400_000, requests_per_minute=1_000),
    "claude-3-5-sonnet-20240620": RateLimitConfig(tokens_per_minute=400_000, requests_per_minute=1_000),

    # Google Gemini (Free tier limits)
    "gemini-pro": RateLimitConfig(tokens_per_minute=1_000_000, requests_per_minute=1_500),
    "gemini-1.5-pro": RateLimitConfig(tokens_per_minute=1_000_000, requests_per_minute=1_500),
    "gemini-1.5-flash": RateLimitConfig(tokens_per_minute=1_000_000, requests_per_minute=1_500),

    # Default conservative limits
    "default": RateLimitConfig(tokens_per_minute=10_000, requests_per_minute=100),
}


def get_rate_limit_config(model_name: str) -> RateLimitConfig:
    """
    Get rate limit configuration for a model

    Args:
        model_name: Model identifier

    Returns:
        RateLimitConfig for the model
    """
    # Try exact match
    if model_name in MODEL_RATE_LIMITS:
        return MODEL_RATE_LIMITS[model_name]

    # Try partial match (e.g., "gpt-4o-2024-08-06" matches "gpt-4o")
    model_lower = model_name.lower()
    for key, config in MODEL_RATE_LIMITS.items():
        if key in model_lower or model_lower.startswith(key):
            logger.debug(f"Matched model '{model_name}' to rate limit key '{key}'")
            return config

    # Fallback to default
    logger.warning(f"No rate limit found for model '{model_name}', using default")
    return MODEL_RATE_LIMITS["default"]


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded"""
    pass


# =============================================================================
# Token Bucket Algorithm
# =============================================================================

class TokenBucket:
    """
    Token bucket algorithm for rate limiting

    How it works:
    - Bucket has a capacity (burst_size)
    - Tokens are added at a constant rate (refill_rate)
    - Each request consumes tokens
    - If not enough tokens, request is throttled

    This allows:
    - Smooth rate limiting
    - Burst handling (short spikes allowed)
    - Fair resource allocation

    Example:
        bucket = TokenBucket(capacity=100, refill_rate=10)  # 10 tokens/sec

        if bucket.consume(15):
            # Request allowed
            make_api_call()
        else:
            # Rate limited, wait
            wait_time = bucket.get_wait_time(15)
            time.sleep(wait_time)
    """

    def __init__(self, capacity: float, refill_rate: float):
        """
        Initialize token bucket

        Args:
            capacity: Maximum tokens in bucket (burst size)
            refill_rate: Tokens added per second
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._tokens = capacity
        self._last_refill = time.time()
        self._lock = RLock()

    def _refill(self):
        """Refill tokens based on elapsed time"""
        now = time.time()
        elapsed = now - self._last_refill

        # Add tokens proportional to elapsed time
        tokens_to_add = elapsed * self.refill_rate
        self._tokens = min(self.capacity, self._tokens + tokens_to_add)
        self._last_refill = now

    def consume(self, tokens: float) -> bool:
        """
        Try to consume tokens

        Args:
            tokens: Number of tokens to consume

        Returns:
            True if tokens consumed, False if not enough tokens
        """
        with self._lock:
            self._refill()

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def get_wait_time(self, tokens: float) -> float:
        """
        Calculate wait time for tokens to be available

        Args:
            tokens: Number of tokens needed

        Returns:
            Wait time in seconds
        """
        with self._lock:
            self._refill()

            if self._tokens >= tokens:
                return 0.0

            tokens_needed = tokens - self._tokens
            return tokens_needed / self.refill_rate

    def get_available_tokens(self) -> float:
        """Get currently available tokens"""
        with self._lock:
            self._refill()
            return self._tokens


# =============================================================================
# Rate Limiter
# =============================================================================

class RateLimiter:
    """
    Rate limiter using dual token buckets (TPM and RPM)

    Features:
    - Separate limits for tokens and requests
    - Automatic throttling with wait
    - Thread-safe operations
    - Metrics tracking

    Example:
        limiter = RateLimiter(
            name="gpt-4o",
            config=RateLimitConfig(
                tokens_per_minute=10_000,
                requests_per_minute=500
            )
        )

        # Before making API call
        limiter.wait_if_needed(tokens=1500)

        # After API call
        limiter.record_request(tokens=1500)
    """

    def __init__(
        self,
        name: str,
        config: RateLimitConfig,
        enable_throttling: bool = True
    ):
        """
        Initialize rate limiter

        Args:
            name: Rate limiter name (for logging)
            config: Rate limit configuration
            enable_throttling: If True, automatically wait when rate limited
        """
        self.name = name
        self.config = config
        self.enable_throttling = enable_throttling

        # Token buckets (rates converted to per-second)
        self.token_bucket = TokenBucket(
            capacity=config.burst_size,
            refill_rate=config.tokens_per_minute / 60.0  # tokens per second
        )
        self.request_bucket = TokenBucket(
            capacity=config.requests_per_minute,
            refill_rate=config.requests_per_minute / 60.0  # requests per second
        )

        # Metrics
        self._total_requests = 0
        self._total_tokens = 0
        self._total_throttled = 0
        self._total_wait_time = 0.0
        self._lock = RLock()

        logger.info(
            f"Rate limiter '{name}' initialized: "
            f"TPM={config.tokens_per_minute:,}, RPM={config.requests_per_minute:,}"
        )

    def check_availability(self, tokens: int = 0) -> tuple[bool, float]:
        """
        Check if request can proceed

        Args:
            tokens: Estimated tokens for request (0 if unknown)

        Returns:
            Tuple of (can_proceed, wait_time)
        """
        token_wait = 0.0
        request_wait = 0.0

        # Check token bucket
        if tokens > 0:
            if not self.token_bucket.consume(0):  # Check without consuming
                token_wait = self.token_bucket.get_wait_time(tokens)

        # Check request bucket
        if not self.request_bucket.consume(0):  # Check without consuming
            request_wait = self.request_bucket.get_wait_time(1)

        max_wait = max(token_wait, request_wait)
        return (max_wait == 0.0, max_wait)

    def wait_if_needed(self, tokens: int = 0):
        """
        Wait if rate limited (automatic throttling)

        Args:
            tokens: Estimated tokens for request (0 if unknown)

        Raises:
            RateLimitExceeded: If throttling is disabled and rate limited
        """
        can_proceed, wait_time = self.check_availability(tokens)

        if can_proceed:
            return

        with self._lock:
            self._total_throttled += 1

        if not self.enable_throttling:
            raise RateLimitExceeded(
                f"Rate limit exceeded for '{self.name}'. "
                f"Wait {wait_time:.2f}s before retrying."
            )

        # Throttle with exponential backoff
        logger.warning(
            f"Rate limit reached for '{self.name}'. "
            f"Throttling for {wait_time:.2f}s..."
        )

        with self._lock:
            self._total_wait_time += wait_time

        time.sleep(wait_time)

    def record_request(self, tokens: int = 0):
        """
        Record a request (consume tokens)

        Args:
            tokens: Actual tokens used (0 if unknown)
        """
        with self._lock:
            # Consume tokens
            if tokens > 0:
                self.token_bucket.consume(tokens)
                self._total_tokens += tokens

            # Consume 1 request
            self.request_bucket.consume(1)
            self._total_requests += 1

    def get_metrics(self) -> Dict[str, Any]:
        """Get rate limiter metrics"""
        with self._lock:
            return {
                "name": self.name,
                "config": {
                    "tpm_limit": self.config.tokens_per_minute,
                    "rpm_limit": self.config.requests_per_minute,
                    "burst_size": self.config.burst_size
                },
                "total_requests": self._total_requests,
                "total_tokens": self._total_tokens,
                "total_throttled": self._total_throttled,
                "total_wait_time": self._total_wait_time,
                "average_wait_time": (
                    self._total_wait_time / self._total_throttled
                    if self._total_throttled > 0 else 0.0
                ),
                "available_tokens": self.token_bucket.get_available_tokens(),
                "available_requests": self.request_bucket.get_available_tokens(),
                "throttle_rate": (
                    self._total_throttled / self._total_requests
                    if self._total_requests > 0 else 0.0
                )
            }


# =============================================================================
# Rate Limiter Manager
# =============================================================================

class RateLimiterManager:
    """
    Manage rate limiters for multiple models

    Features:
    - Centralized rate limiting across all agents
    - Per-model rate limiters
    - System-wide metrics
    """

    def __init__(self):
        """Initialize manager"""
        self._limiters: Dict[str, RateLimiter] = {}
        self._lock = RLock()

    def get_or_create(
        self,
        model: str,
        config: Optional[RateLimitConfig] = None,
        enable_throttling: bool = True
    ) -> RateLimiter:
        """
        Get existing or create new rate limiter

        Args:
            model: Model name
            config: Optional rate limit config (uses defaults if None)
            enable_throttling: Enable automatic throttling

        Returns:
            RateLimiter instance
        """
        with self._lock:
            if model not in self._limiters:
                if config is None:
                    config = get_rate_limit_config(model)

                self._limiters[model] = RateLimiter(
                    name=model,
                    config=config,
                    enable_throttling=enable_throttling
                )

            return self._limiters[model]

    def get_limiter(self, model: str) -> Optional[RateLimiter]:
        """Get existing rate limiter"""
        return self._limiters.get(model)

    def get_all_limiters(self) -> Dict[str, RateLimiter]:
        """Get all rate limiters"""
        with self._lock:
            return self._limiters.copy()

    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all rate limiters"""
        with self._lock:
            return {
                name: limiter.get_metrics()
                for name, limiter in self._limiters.items()
            }

    def get_system_summary(self) -> Dict[str, Any]:
        """Get system-wide rate limit summary"""
        with self._lock:
            total_throttled = sum(
                limiter._total_throttled
                for limiter in self._limiters.values()
            )
            total_wait_time = sum(
                limiter._total_wait_time
                for limiter in self._limiters.values()
            )
            total_requests = sum(
                limiter._total_requests
                for limiter in self._limiters.values()
            )

            return {
                "total_limiters": len(self._limiters),
                "total_requests": total_requests,
                "total_throttled": total_throttled,
                "total_wait_time": total_wait_time,
                "overall_throttle_rate": (
                    total_throttled / total_requests
                    if total_requests > 0 else 0.0
                )
            }


# Singleton instance
_rate_limiter_manager: Optional[RateLimiterManager] = None


def get_rate_limiter_manager() -> RateLimiterManager:
    """Get global rate limiter manager instance"""
    global _rate_limiter_manager
    if _rate_limiter_manager is None:
        _rate_limiter_manager = RateLimiterManager()
    return _rate_limiter_manager
