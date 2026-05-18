"""Error recovery strategies and handlers"""

from typing import Optional, Dict, Any, Callable
from functools import wraps
import traceback
from pathlib import Path

from rich.console import Console

from agent_os.cli.ui.formatters import format_error
from agent_os.utils.errors import AgentConfigError
from agent_os.utils.cost_tracker import BudgetExceededError
from agent_os.utils.circuit_breaker import CircuitBreakerError
from agent_os.utils.rate_limiter import RateLimitExceeded
from agent_os.utils.retry import MaxRetriesExceeded
from agent_os.utils.timeout import TimeoutError

console = Console()


def graceful_error_handler(
    show_traceback: bool = False,
    log_file: Optional[Path] = None
):
    """
    Decorator for graceful error handling with user-friendly messages.

    Args:
        show_traceback: Show full traceback to user
        log_file: Path to error log file
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            import typer
            try:
                return func(*args, **kwargs)
            except typer.Exit:
                # Let typer exits pass through (for CLI exit codes)
                raise
            except KeyboardInterrupt:
                console.print("\n[yellow]Operation cancelled by user[/yellow]")
                return None
            except AgentConfigError as e:
                console.print(format_error(
                    f"Configuration error: {e}",
                    suggestions=[
                        "Check your agent configuration file",
                        "Ensure all required fields are present",
                        "Validate with 'agent_os info agent <name>'",
                    ]
                ))
                _log_error(e, log_file)
                return None
            except BudgetExceededError as e:
                console.print(format_error(
                    f"Budget exceeded: {e}",
                    suggestions=[
                        "Increase the budget limit",
                        "Use a cheaper model",
                        "Simplify your query",
                    ]
                ))
                _log_error(e, log_file)
                return None
            except TimeoutError as e:
                console.print(format_error(
                    f"Operation timed out: {e}",
                    suggestions=[
                        "Increase max_execution_time in agent config",
                        "Break down the task into smaller steps",
                        "Check for infinite loops in agent logic",
                    ]
                ))
                _log_error(e, log_file)
                return None
            except CircuitBreakerError as e:
                console.print(format_error(
                    f"Circuit breaker open: {e}",
                    suggestions=[
                        "Wait a few minutes and try again",
                        "Check the error logs for root cause",
                        "Restart the agent if the issue persists",
                    ]
                ))
                _log_error(e, log_file)
                return None
            except RateLimitExceeded as e:
                console.print(format_error(
                    f"Rate limit exceeded: {e}",
                    suggestions=[
                        "Wait before retrying",
                        "Reduce request frequency",
                        "Check your API quota",
                    ]
                ))
                _log_error(e, log_file)
                return None
            except MaxRetriesExceeded as e:
                console.print(format_error(
                    f"Max retries exceeded: {e}",
                    suggestions=[
                        "Check the error logs for the underlying issue",
                        "Verify API credentials and connectivity",
                        "Increase retry limits if appropriate",
                    ]
                ))
                _log_error(e, log_file)
                return None
            except FileNotFoundError as e:
                console.print(format_error(
                    f"File not found: {e}",
                    suggestions=[
                        "Check the file path",
                        "Ensure the resource exists",
                        "Use 'agent_os list' to see available resources",
                    ]
                ))
                _log_error(e, log_file)
                return None
            except PermissionError as e:
                console.print(format_error(
                    f"Permission denied: {e}",
                    suggestions=[
                        "Check file permissions",
                        "Run with appropriate privileges",
                        "Ensure the directory is writable",
                    ]
                ))
                _log_error(e, log_file)
                return None
            except Exception as e:
                error_msg = f"Unexpected error: {e}"
                if show_traceback:
                    error_msg += f"\n\n{traceback.format_exc()}"

                console.print(format_error(
                    error_msg,
                    suggestions=[
                        "Check the error logs for more details",
                        "Report this issue if it persists",
                        "Run with --debug for more information",
                    ]
                ))
                _log_error(e, log_file)
                return None

        return wrapper
    return decorator


def _log_error(error: Exception, log_file: Optional[Path]):
    """Log error to file"""
    if not log_file:
        return

    try:
        from datetime import datetime

        log_file.parent.mkdir(parents=True, exist_ok=True)

        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"Error Type: {type(error).__name__}\n")
            f.write(f"Error Message: {str(error)}\n")
            f.write(f"Traceback:\n{traceback.format_exc()}\n")
    except Exception as log_error:
        console.print(f"[dim red]Warning: Failed to log error: {log_error}[/dim red]")


def suggest_recovery(error_type: str, context: Optional[Dict[str, Any]] = None) -> list[str]:
    """
    Suggest recovery actions based on error type and context.

    Args:
        error_type: Type of error encountered
        context: Additional context about the error

    Returns:
        List of recovery suggestions
    """
    suggestions = {
        "config_error": [
            "Validate your configuration file",
            "Check for missing or invalid fields",
            "Compare with working examples",
        ],
        "budget_exceeded": [
            "Increase the budget limit in settings",
            "Switch to a cheaper model (e.g., gpt-4o-mini)",
            "Reduce max_iterations to use fewer tokens",
        ],
        "timeout": [
            "Increase max_execution_time in agent config",
            "Simplify the query or break it into steps",
            "Check for blocking operations in tools",
        ],
        "circuit_breaker": [
            "Wait 5-10 minutes before retrying",
            "Check error logs to identify root cause",
            "Verify API connectivity and credentials",
        ],
        "rate_limit": [
            "Wait before retrying (check Retry-After header)",
            "Reduce request frequency",
            "Upgrade your API plan if needed",
        ],
        "tool_error": [
            "Verify tool configuration",
            "Check tool permissions and credentials",
            "Test tool in isolation",
        ],
        "memory_error": [
            "Reduce context window size",
            "Clear old conversation history",
            "Use memory trimming settings",
        ],
        "network_error": [
            "Check internet connectivity",
            "Verify API endpoint URLs",
            "Check firewall and proxy settings",
        ],
    }

    base_suggestions = suggestions.get(error_type, [
        "Check the error logs for details",
        "Verify your configuration",
        "Contact support if the issue persists",
    ])

    if context:
        if context.get("agent_name"):
            base_suggestions.append(f"Check agent '{context['agent_name']}' configuration")
        if context.get("tool_name"):
            base_suggestions.append(f"Verify tool '{context['tool_name']}' is properly configured")

    return base_suggestions


def validate_before_execution(
    agent_config: Dict[str, Any],
    tool_registry,
    required_fields: Optional[list[str]] = None
) -> tuple[bool, Optional[str]]:
    """
    Validate agent configuration before execution.

    Args:
        agent_config: Agent configuration dictionary
        tool_registry: Tool registry instance
        required_fields: List of required config fields

    Returns:
        Tuple of (is_valid, error_message)
    """
    required = required_fields or ["name", "tools", "model"]

    for field in required:
        if field not in agent_config:
            return False, f"Missing required field: {field}"

    tools = agent_config.get("tools", [])
    if not tools:
        return False, "Agent must have at least one tool"

    available_tools = tool_registry.list_all()
    invalid_tools = [t for t in tools if t not in available_tools]
    if invalid_tools:
        return False, f"Invalid tools: {', '.join(invalid_tools)}"

    temperature = agent_config.get("temperature", 0.0)
    if not 0.0 <= temperature <= 2.0:
        return False, f"Temperature must be between 0.0 and 2.0, got {temperature}"

    return True, None
