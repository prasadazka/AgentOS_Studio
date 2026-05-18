"""
Logging configuration for Agent_OS with structured context support.

Fix #11: Improve Logging with Structured Context
"""

import logging
import sys
import uuid
from typing import Optional, Dict, Any
from contextvars import ContextVar


# Context variables for tracking deployment/operation context
_correlation_id: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)
_deployment_context: ContextVar[Dict[str, Any]] = ContextVar('deployment_context', default={})


class StructuredFormatter(logging.Formatter):
    """
    Custom formatter that adds structured context fields to log records.

    Includes correlation ID, deployment context, and custom fields for better
    log aggregation and debugging.
    """

    def format(self, record: logging.LogRecord) -> str:
        # Add correlation ID if available
        correlation_id = _correlation_id.get()
        if correlation_id:
            record.correlation_id = correlation_id

        # Add deployment context fields
        context = _deployment_context.get()
        for key, value in context.items():
            if not hasattr(record, key):
                setattr(record, key, value)

        return super().format(record)


def setup_logging(
    level: int = logging.INFO,
    format_string: Optional[str] = None,
    log_file: Optional[str] = None,
    structured: bool = True
) -> logging.Logger:
    """
    Setup logging for Agent_OS with optional structured context.

    Args:
        level: Logging level (default: INFO)
        format_string: Custom format string
        log_file: Optional file path for logging
        structured: Enable structured logging with context fields

    Returns:
        Configured logger instance
    """
    if format_string is None:
        if structured:
            # Enhanced format with structured context
            format_string = (
                "%(asctime)s - %(name)s - %(levelname)s - "
                "[%(correlation_id)s] - %(message)s"
            )
        else:
            format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    logger = logging.getLogger("agent_os")
    logger.setLevel(level)

    # Clear existing handlers
    logger.handlers.clear()

    # Choose formatter
    formatter_class = StructuredFormatter if structured else logging.Formatter

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter_class(format_string))
    logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter_class(format_string))
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a specific module"""
    return logging.getLogger(f"agent_os.{name}")


def set_correlation_id(correlation_id: Optional[str] = None) -> str:
    """
    Set correlation ID for the current context.

    Correlation IDs help track related log messages across a deployment
    or operation, making debugging easier.

    Args:
        correlation_id: Custom correlation ID, or auto-generate if None

    Returns:
        The correlation ID that was set
    """
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())[:8]

    _correlation_id.set(correlation_id)
    return correlation_id


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID"""
    return _correlation_id.get()


def set_deployment_context(**kwargs: Any) -> None:
    """
    Set deployment context fields that will be added to all log records.

    Example:
        set_deployment_context(
            project="my-app",
            phase="analysis",
            agent="CodeAnalyzer"
        )

    Args:
        **kwargs: Key-value pairs to add to deployment context
    """
    context = _deployment_context.get().copy()
    context.update(kwargs)
    _deployment_context.set(context)


def clear_deployment_context() -> None:
    """Clear all deployment context fields"""
    _deployment_context.set({})


def get_deployment_context() -> Dict[str, Any]:
    """Get the current deployment context"""
    return _deployment_context.get().copy()


def log_with_context(
    logger: logging.Logger,
    level: int,
    message: str,
    **context: Any
) -> None:
    """
    Log a message with additional context fields.

    Args:
        logger: Logger instance
        level: Log level (logging.INFO, logging.ERROR, etc.)
        message: Log message
        **context: Additional context fields to include
    """
    extra = context.copy()

    # Add correlation ID
    correlation_id = get_correlation_id()
    if correlation_id:
        extra['correlation_id'] = correlation_id

    # Add deployment context
    extra.update(get_deployment_context())

    logger.log(level, message, extra=extra)
