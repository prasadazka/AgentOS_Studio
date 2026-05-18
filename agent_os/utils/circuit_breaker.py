"""
Circuit Breaker Pattern Implementation for Agent_OS

Prevents cascading failures by detecting failing services and stopping
requests temporarily. Essential for production LLM API reliability.

Features:
- Three states: CLOSED, OPEN, HALF_OPEN
- Configurable failure threshold and timeout
- Automatic recovery detection
- Per-service circuit breakers
- Metrics tracking (failures, successes, state changes)
"""

import time
from enum import Enum
from typing import Callable, Any, Optional, Dict
from functools import wraps
from datetime import datetime, timedelta
from threading import RLock

from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Circuit Breaker States
# =============================================================================

class CircuitState(str, Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation, requests allowed
    OPEN = "open"          # Failure threshold exceeded, requests blocked
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is OPEN"""
    pass


# =============================================================================
# Circuit Breaker Implementation
# =============================================================================

class CircuitBreaker:
    """
    Circuit breaker for preventing cascading failures

    States:
    - CLOSED: Normal operation, all requests go through
    - OPEN: Too many failures, all requests blocked (fast-fail)
    - HALF_OPEN: Testing recovery, limited requests allowed

    Transitions:
    - CLOSED → OPEN: When failure_threshold exceeded
    - OPEN → HALF_OPEN: After timeout_duration
    - HALF_OPEN → CLOSED: When success_threshold met
    - HALF_OPEN → OPEN: If any failure occurs

    Example:
        cb = CircuitBreaker(
            name="openai_api",
            failure_threshold=5,
            timeout_duration=60,
            success_threshold=2
        )

        @cb.call
        def call_openai():
            return openai.chat.completions.create(...)
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout_duration: float = 60.0,
        success_threshold: int = 2,
        expected_exception: type = Exception
    ):
        """
        Initialize circuit breaker

        Args:
            name: Circuit breaker name (for logging/metrics)
            failure_threshold: Number of failures before opening circuit
            timeout_duration: Seconds to wait before attempting recovery (OPEN → HALF_OPEN)
            success_threshold: Consecutive successes needed to close circuit in HALF_OPEN
            expected_exception: Exception type that triggers circuit breaker
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout_duration = timeout_duration
        self.success_threshold = success_threshold
        self.expected_exception = expected_exception

        # State
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._last_state_change: float = time.time()

        # Metrics
        self._total_calls = 0
        self._total_failures = 0
        self._total_successes = 0
        self._total_rejected = 0

        # Thread safety (RLock allows reentrant locking)
        self._lock = RLock()

        logger.info(f"Circuit breaker '{name}' initialized: "
                   f"failure_threshold={failure_threshold}, "
                   f"timeout={timeout_duration}s, "
                   f"success_threshold={success_threshold}")

    @property
    def state(self) -> CircuitState:
        """Get current circuit state"""
        with self._lock:
            self._check_and_update_state()
            return self._state

    def _check_and_update_state(self):
        """Check if state should transition (OPEN → HALF_OPEN)"""
        if self._state == CircuitState.OPEN and self._last_failure_time:
            if time.time() - self._last_failure_time >= self.timeout_duration:
                self._transition_to(CircuitState.HALF_OPEN)
                logger.info(f"Circuit breaker '{self.name}' attempting recovery (HALF_OPEN)")

    def _transition_to(self, new_state: CircuitState):
        """Transition to new state"""
        old_state = self._state
        self._state = new_state
        self._last_state_change = time.time()

        # Reset counters on state change
        if new_state == CircuitState.HALF_OPEN:
            self._success_count = 0
        elif new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0

        logger.warning(f"Circuit breaker '{self.name}' state: {old_state.value} → {new_state.value}")

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerError: If circuit is OPEN
            Exception: Original exception if function fails
        """
        with self._lock:
            self._total_calls += 1
            current_state = self.state  # Triggers state check

            # OPEN: Reject immediately
            if current_state == CircuitState.OPEN:
                self._total_rejected += 1
                error_msg = (
                    f"Circuit breaker '{self.name}' is OPEN "
                    f"(failure_count={self._failure_count}/{self.failure_threshold}). "
                    f"Retry in {self._get_remaining_timeout():.1f}s"
                )
                logger.warning(error_msg)
                raise CircuitBreakerError(error_msg)

        # Execute function
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result

        except self.expected_exception as e:
            self._on_failure(e)
            raise

    def _on_success(self):
        """Handle successful call"""
        with self._lock:
            self._total_successes += 1

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                logger.debug(f"Circuit breaker '{self.name}' recovery progress: "
                           f"{self._success_count}/{self.success_threshold} successes")

                if self._success_count >= self.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
                    logger.info(f"Circuit breaker '{self.name}' recovered (CLOSED)")

            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0

    def _on_failure(self, exception: Exception):
        """Handle failed call"""
        with self._lock:
            self._total_failures += 1
            self._failure_count += 1
            self._last_failure_time = time.time()

            logger.warning(f"Circuit breaker '{self.name}' failure: {exception.__class__.__name__}: {str(exception)[:100]}")

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in HALF_OPEN reopens circuit
                self._transition_to(CircuitState.OPEN)
                logger.warning(f"Circuit breaker '{self.name}' recovery failed, reopening")

            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._transition_to(CircuitState.OPEN)
                    logger.error(
                        f"Circuit breaker '{self.name}' OPENED "
                        f"(failures: {self._failure_count}/{self.failure_threshold})"
                    )

    def _get_remaining_timeout(self) -> float:
        """Get remaining timeout before retry attempt"""
        if self._last_failure_time:
            elapsed = time.time() - self._last_failure_time
            return max(0, self.timeout_duration - elapsed)
        return 0

    def reset(self):
        """Manually reset circuit breaker to CLOSED state"""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            logger.info(f"Circuit breaker '{self.name}' manually reset")

    def get_metrics(self) -> Dict[str, Any]:
        """Get circuit breaker metrics"""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "total_calls": self._total_calls,
                "total_successes": self._total_successes,
                "total_failures": self._total_failures,
                "total_rejected": self._total_rejected,
                "failure_rate": self._total_failures / self._total_calls if self._total_calls > 0 else 0,
                "rejection_rate": self._total_rejected / self._total_calls if self._total_calls > 0 else 0,
                "last_failure_time": self._last_failure_time,
                "remaining_timeout": self._get_remaining_timeout() if self._state == CircuitState.OPEN else None,
                "uptime_seconds": time.time() - self._last_state_change
            }

    def __str__(self) -> str:
        """String representation"""
        metrics = self.get_metrics()
        return (
            f"CircuitBreaker(name='{self.name}', "
            f"state={metrics['state']}, "
            f"failures={metrics['failure_count']}/{self.failure_threshold}, "
            f"calls={metrics['total_calls']}, "
            f"failure_rate={metrics['failure_rate']:.1%})"
        )


# =============================================================================
# Circuit Breaker Manager
# =============================================================================

class CircuitBreakerManager:
    """
    Manage multiple circuit breakers

    Features:
    - Centralized circuit breaker registry
    - Per-service circuit breakers
    - Global metrics and health status
    - LRU-based cleanup to prevent memory leaks
    """

    def __init__(self, max_breakers: int = 1000):
        """
        Initialize circuit breaker manager

        Args:
            max_breakers: Maximum number of circuit breakers to maintain.
                         Older breakers automatically evicted via LRU when exceeded.
        """
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._access_times: Dict[str, float] = {}  # Track last access time for LRU
        self._max_breakers = max_breakers
        self._lock = RLock()

        logger.info(
            f"Circuit breaker manager initialized (max_breakers: {max_breakers})"
        )

    def _cleanup_old_breakers(self):
        """
        Remove least recently used circuit breakers when limit exceeded

        This prevents memory leaks in multi-tenant or dynamic agent scenarios
        where circuit breakers are created per-user or per-session.
        """
        if len(self._breakers) <= self._max_breakers:
            return

        # Remove oldest 10% of breakers
        num_to_remove = max(1, int(self._max_breakers * 0.1))

        # Sort by access time (oldest first)
        sorted_breakers = sorted(
            self._access_times.items(),
            key=lambda x: x[1]
        )

        # Remove oldest breakers
        for name, _ in sorted_breakers[:num_to_remove]:
            if name in self._breakers:
                del self._breakers[name]
                del self._access_times[name]
                logger.info(
                    f"Evicted circuit breaker '{name}' (LRU cleanup, "
                    f"total: {len(self._breakers)})"
                )

    def get_or_create(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout_duration: float = 60.0,
        success_threshold: int = 2,
        expected_exception: type = Exception
    ) -> CircuitBreaker:
        """
        Get existing circuit breaker or create new one

        Args:
            name: Circuit breaker name
            failure_threshold: Failures before opening
            timeout_duration: Timeout before recovery attempt
            success_threshold: Successes needed to close
            expected_exception: Exception type to catch

        Returns:
            CircuitBreaker instance
        """
        with self._lock:
            # Update access time
            self._access_times[name] = time.time()

            if name not in self._breakers:
                # Cleanup old breakers if needed
                self._cleanup_old_breakers()

                self._breakers[name] = CircuitBreaker(
                    name=name,
                    failure_threshold=failure_threshold,
                    timeout_duration=timeout_duration,
                    success_threshold=success_threshold,
                    expected_exception=expected_exception
                )
                logger.info(f"Created circuit breaker: {name}")

            return self._breakers[name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Get circuit breaker by name"""
        with self._lock:
            if name in self._breakers:
                # Update access time for LRU
                self._access_times[name] = time.time()
            return self._breakers.get(name)

    def reset(self, name: str):
        """Reset circuit breaker by name"""
        breaker = self.get(name)
        if breaker:
            breaker.reset()

    def reset_all(self):
        """Reset all circuit breakers"""
        with self._lock:
            for breaker in self._breakers.values():
                breaker.reset()
            logger.info("All circuit breakers reset")

    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all circuit breakers"""
        return {name: breaker.get_metrics() for name, breaker in self._breakers.items()}

    def get_health_summary(self) -> Dict[str, Any]:
        """Get overall health summary"""
        metrics = self.get_all_metrics()
        total_breakers = len(metrics)
        open_breakers = sum(1 for m in metrics.values() if m["state"] == "open")
        half_open_breakers = sum(1 for m in metrics.values() if m["state"] == "half_open")

        return {
            "total_breakers": total_breakers,
            "healthy": total_breakers - open_breakers - half_open_breakers,
            "degraded": half_open_breakers,
            "failed": open_breakers,
            "overall_health": "healthy" if open_breakers == 0 else "degraded" if open_breakers < total_breakers else "critical"
        }


# Global circuit breaker manager
_global_manager = CircuitBreakerManager()


def get_circuit_breaker_manager() -> CircuitBreakerManager:
    """Get global circuit breaker manager"""
    return _global_manager


# =============================================================================
# Decorator
# =============================================================================

def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    timeout_duration: float = 60.0,
    success_threshold: int = 2,
    expected_exception: type = Exception
):
    """
    Decorator to add circuit breaker protection to function

    Args:
        name: Circuit breaker name
        failure_threshold: Failures before opening
        timeout_duration: Timeout before recovery attempt (seconds)
        success_threshold: Successes needed to close
        expected_exception: Exception type to catch

    Example:
        @circuit_breaker(name="openai_api", failure_threshold=3, timeout_duration=30)
        def call_openai(prompt):
            return openai.chat.completions.create(...)
    """

    def decorator(func: Callable) -> Callable:
        cb = get_circuit_breaker_manager().get_or_create(
            name=name,
            failure_threshold=failure_threshold,
            timeout_duration=timeout_duration,
            success_threshold=success_threshold,
            expected_exception=expected_exception
        )

        @wraps(func)
        def wrapper(*args, **kwargs):
            return cb.call(func, *args, **kwargs)

        # Attach circuit breaker for inspection
        wrapper._circuit_breaker = cb

        return wrapper

    return decorator
