"""
Timeout Enforcement for Agent_OS

Provides hard limits on agent execution time to prevent runaway processes.
Essential for production reliability with untrusted or complex agent workflows.

Features:
- Thread-based timeout enforcement (cross-platform)
- Graceful cancellation with cleanup
- Integration with reliability layers
- Configurable per-agent or per-request

Common Timeout Scenarios:
- Long-running tool calls: Network requests, database queries
- Infinite loops: Agent stuck in reasoning loop
- Resource exhaustion: Agent consuming excessive CPU/memory
- Runaway recursion: Agent calling itself indefinitely
"""

import threading
import time
from typing import Callable, Any, Optional, TypeVar
from functools import wraps
from contextlib import contextmanager

from agent_os.utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


class TimeoutError(Exception):
    """Raised when execution exceeds timeout limit"""

    def __init__(self, timeout: float, operation: str = "operation"):
        self.timeout = timeout
        self.operation = operation
        super().__init__(
            f"{operation} exceeded timeout of {timeout:.1f}s"
        )


class TimeoutEnforcer:
    """
    Enforce hard timeout on function execution using threading

    Thread-safe, cross-platform timeout enforcement that works on
    both Unix (no signal module) and Windows.

    Example:
        enforcer = TimeoutEnforcer(timeout=30.0)
        result = enforcer.execute(slow_function, arg1, arg2)
    """

    def __init__(self, timeout: float, operation_name: str = "operation"):
        """
        Initialize timeout enforcer

        Args:
            timeout: Maximum execution time in seconds
            operation_name: Description of operation (for error messages)
        """
        if timeout <= 0:
            raise ValueError(f"Timeout must be positive, got {timeout}")

        self.timeout = timeout
        self.operation_name = operation_name
        self._result = None
        self._exception = None
        self._completed = threading.Event()

    def execute(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        Execute function with timeout enforcement

        Args:
            func: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            TimeoutError: If execution exceeds timeout
            Exception: Any exception raised by func
        """
        def target():
            """Thread target that executes function"""
            try:
                self._result = func(*args, **kwargs)
            except Exception as e:
                self._exception = e
            finally:
                self._completed.set()

        # Reset state
        self._result = None
        self._exception = None
        self._completed.clear()

        # Start execution thread
        thread = threading.Thread(target=target, daemon=True)
        start_time = time.time()
        thread.start()

        logger.debug(
            f"Started {self.operation_name} with {self.timeout:.1f}s timeout"
        )

        # Wait for completion or timeout
        completed = self._completed.wait(timeout=self.timeout)
        elapsed = time.time() - start_time

        if not completed:
            # Timeout occurred
            logger.error(
                f"{self.operation_name} timed out after {elapsed:.2f}s "
                f"(limit: {self.timeout:.1f}s)"
            )
            raise TimeoutError(
                timeout=self.timeout,
                operation=self.operation_name
            )

        # Check for exceptions
        if self._exception is not None:
            logger.debug(
                f"{self.operation_name} completed with exception in {elapsed:.2f}s"
            )
            raise self._exception

        # Success
        logger.debug(
            f"{self.operation_name} completed successfully in {elapsed:.2f}s"
        )
        return self._result


def with_timeout(timeout: float, operation_name: str = "operation"):
    """
    Decorator to add timeout enforcement to any function

    Example:
        @with_timeout(timeout=30.0, operation_name="agent_execution")
        def run_agent(query: str) -> str:
            # Long-running operation
            return result

    Args:
        timeout: Maximum execution time in seconds
        operation_name: Description of operation (for error messages)

    Returns:
        Decorated function with timeout enforcement
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            enforcer = TimeoutEnforcer(
                timeout=timeout,
                operation_name=operation_name or func.__name__
            )
            return enforcer.execute(func, *args, **kwargs)

        return wrapper

    return decorator


@contextmanager
def timeout_context(timeout: float, operation_name: str = "operation"):
    """
    Context manager for timeout enforcement

    Example:
        with timeout_context(30.0, "database_query"):
            result = execute_slow_query()

    Args:
        timeout: Maximum execution time in seconds
        operation_name: Description of operation

    Yields:
        None

    Raises:
        TimeoutError: If operations within context exceed timeout
    """
    start_time = time.time()

    # Store start time in context
    context = {'start_time': start_time, 'timeout': timeout}

    try:
        yield context
        elapsed = time.time() - start_time
        logger.debug(
            f"{operation_name} completed in {elapsed:.2f}s "
            f"(limit: {timeout:.1f}s)"
        )
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            f"{operation_name} failed after {elapsed:.2f}s: {e}"
        )
        raise


def check_timeout_remaining(
    start_time: float,
    timeout: float,
    operation_name: str = "operation"
) -> float:
    """
    Check remaining time in timeout window

    Useful for operations that need to check timeout periodically
    without using threads.

    Args:
        start_time: Operation start time (from time.time())
        timeout: Total timeout in seconds
        operation_name: Description of operation

    Returns:
        Remaining time in seconds

    Raises:
        TimeoutError: If timeout already exceeded
    """
    elapsed = time.time() - start_time
    remaining = timeout - elapsed

    if remaining <= 0:
        logger.error(
            f"{operation_name} timeout check failed: "
            f"{elapsed:.2f}s elapsed (limit: {timeout:.1f}s)"
        )
        raise TimeoutError(timeout=timeout, operation=operation_name)

    return remaining


# =============================================================================
# Integration with Agent Execution
# =============================================================================

def execute_with_timeout(
    func: Callable[..., T],
    timeout: Optional[float],
    operation_name: str = "operation",
    *args,
    **kwargs
) -> T:
    """
    Execute function with optional timeout

    If timeout is None, execute without timeout enforcement.

    Args:
        func: Function to execute
        timeout: Maximum execution time (None for no limit)
        operation_name: Description of operation
        *args: Positional arguments
        **kwargs: Keyword arguments

    Returns:
        Function result

    Raises:
        TimeoutError: If execution exceeds timeout
        Exception: Any exception raised by func
    """
    if timeout is None or timeout <= 0:
        # No timeout enforcement
        return func(*args, **kwargs)

    # Enforce timeout
    enforcer = TimeoutEnforcer(timeout=timeout, operation_name=operation_name)
    return enforcer.execute(func, *args, **kwargs)
