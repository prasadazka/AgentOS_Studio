"""
Graceful Shutdown for Agent_OS

Provides clean resource cleanup and shutdown mechanisms.
Essential for production deployments to prevent resource leaks
and ensure data integrity during shutdown.

Features:
- Context manager support for agents
- Resource cleanup for all managers
- Thread-safe shutdown procedures
- Signal handling for graceful termination

Common Shutdown Scenarios:
- Application restart: Clean up resources before restart
- Container termination: Kubernetes pod shutdown
- Development testing: Clean up between test runs
- Service maintenance: Graceful service stop
"""

import atexit
import signal
import sys
import threading
from typing import List, Callable, Optional
from contextlib import contextmanager

from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Shutdown Handler
# =============================================================================

class ShutdownHandler:
    """
    Centralized shutdown handler for Agent_OS

    Manages cleanup callbacks and ensures orderly shutdown
    of all resources.

    Thread-safe and supports multiple cleanup callbacks.
    """

    def __init__(self):
        """Initialize shutdown handler"""
        self._callbacks: List[Callable] = []
        self._lock = threading.RLock()
        self._shutdown_initiated = False
        self._shutdown_complete = False

        logger.info("Shutdown handler initialized")

    def register_callback(self, callback: Callable, name: Optional[str] = None):
        """
        Register a cleanup callback

        Args:
            callback: Function to call during shutdown
            name: Optional name for logging
        """
        with self._lock:
            if self._shutdown_initiated:
                logger.warning(
                    f"Cannot register callback '{name or callback.__name__}' "
                    f"after shutdown initiated"
                )
                return

            self._callbacks.append(callback)
            logger.debug(f"Registered shutdown callback: {name or callback.__name__}")

    def unregister_callback(self, callback: Callable):
        """
        Unregister a cleanup callback

        Args:
            callback: Function to remove
        """
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)
                logger.debug(f"Unregistered shutdown callback: {callback.__name__}")

    def shutdown(self):
        """
        Execute all cleanup callbacks

        Thread-safe and idempotent (can be called multiple times).
        """
        with self._lock:
            if self._shutdown_complete:
                logger.debug("Shutdown already complete, skipping")
                return

            if self._shutdown_initiated:
                logger.debug("Shutdown already in progress, waiting...")
                return

            self._shutdown_initiated = True
            logger.info("Initiating graceful shutdown...")

        # Execute callbacks outside lock to prevent deadlocks
        callbacks = list(self._callbacks)
        logger.info(f"Executing {len(callbacks)} shutdown callbacks...")

        for i, callback in enumerate(callbacks, 1):
            try:
                logger.debug(f"[{i}/{len(callbacks)}] Running callback: {callback.__name__}")
                callback()
                logger.debug(f"[{i}/{len(callbacks)}] Completed: {callback.__name__}")
            except Exception as e:
                logger.error(
                    f"Error in shutdown callback {callback.__name__}: {e}",
                    exc_info=True
                )

        with self._lock:
            self._shutdown_complete = True
            logger.info("Graceful shutdown complete")

    def is_shutdown_initiated(self) -> bool:
        """Check if shutdown has been initiated"""
        with self._lock:
            return self._shutdown_initiated


# Global shutdown handler instance
_global_shutdown_handler = ShutdownHandler()


def get_shutdown_handler() -> ShutdownHandler:
    """Get global shutdown handler instance"""
    return _global_shutdown_handler


# =============================================================================
# Manager Cleanup Functions
# =============================================================================

def cleanup_circuit_breakers():
    """Clean up all circuit breakers"""
    try:
        from agent_os.utils.circuit_breaker import get_circuit_breaker_manager

        manager = get_circuit_breaker_manager()
        count = len(manager._breakers)

        if count > 0:
            logger.info(f"Cleaning up {count} circuit breakers...")
            manager._breakers.clear()
            manager._access_times.clear()
            logger.info(f"Cleaned up {count} circuit breakers")
    except Exception as e:
        logger.error(f"Error cleaning up circuit breakers: {e}")


def cleanup_cost_trackers():
    """Clean up all cost trackers"""
    try:
        from agent_os.utils.cost_tracker import get_cost_tracker_manager

        manager = get_cost_tracker_manager()
        count = len(manager._trackers)

        if count > 0:
            logger.info(f"Cleaning up {count} cost trackers...")
            manager._trackers.clear()
            manager._access_times.clear()
            logger.info(f"Cleaned up {count} cost trackers")
    except Exception as e:
        logger.error(f"Error cleaning up cost trackers: {e}")


def cleanup_rate_limiters():
    """Clean up all rate limiters"""
    try:
        from agent_os.utils.rate_limiter import get_rate_limiter_manager

        manager = get_rate_limiter_manager()
        count = len(manager._limiters)

        if count > 0:
            logger.info(f"Cleaning up {count} rate limiters...")
            manager._limiters.clear()
            # Note: RateLimiterManager doesn't have _access_times (no LRU cleanup)
            logger.info(f"Cleaned up {count} rate limiters")
    except Exception as e:
        logger.error(f"Error cleaning up rate limiters: {e}")


def cleanup_all_managers():
    """Clean up all Agent_OS managers"""
    logger.info("Cleaning up all Agent_OS managers...")
    cleanup_circuit_breakers()
    cleanup_cost_trackers()
    cleanup_rate_limiters()
    logger.info("All managers cleaned up")


# =============================================================================
# Signal Handling
# =============================================================================

def setup_signal_handlers():
    """
    Setup signal handlers for graceful shutdown

    Handles SIGTERM and SIGINT (Ctrl+C) to trigger cleanup.
    """
    def signal_handler(signum, frame):
        signal_name = signal.Signals(signum).name
        logger.info(f"Received signal {signal_name}, initiating shutdown...")
        get_shutdown_handler().shutdown()
        sys.exit(0)

    # Register handlers for common termination signals
    try:
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        logger.debug("Signal handlers registered (SIGTERM, SIGINT)")
    except (AttributeError, ValueError) as e:
        # Windows doesn't support SIGTERM
        logger.debug(f"Could not register all signal handlers: {e}")
        try:
            signal.signal(signal.SIGINT, signal_handler)
            logger.debug("Signal handler registered (SIGINT only)")
        except Exception as e:
            logger.warning(f"Could not register signal handlers: {e}")


# =============================================================================
# Context Managers
# =============================================================================

@contextmanager
def agent_context(*agents):
    """
    Context manager for agents with automatic cleanup

    Example:
        with agent_context(agent1, agent2):
            result1 = agent1.run("query")
            result2 = agent2.run("query")
        # Agents automatically cleaned up

    Args:
        *agents: One or more BaseAgent instances

    Yields:
        Agents (or single agent if only one provided)
    """
    try:
        # Yield agents
        if len(agents) == 1:
            yield agents[0]
        else:
            yield agents

    finally:
        # Clean up agents
        logger.debug(f"Cleaning up {len(agents)} agents...")
        for agent in agents:
            try:
                if hasattr(agent, 'cleanup'):
                    agent.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up agent '{agent.name}': {e}")


# =============================================================================
# Initialization
# =============================================================================

# Register cleanup on module import
atexit.register(lambda: get_shutdown_handler().shutdown())

# Register global cleanup callbacks
get_shutdown_handler().register_callback(cleanup_all_managers, name="cleanup_all_managers")

logger.debug("Shutdown module initialized with atexit handler")
