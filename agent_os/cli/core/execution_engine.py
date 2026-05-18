"""
Execution Engine for Robust Agent Execution

Comprehensive error handling with graceful degradation and recovery suggestions.
Zero crashes - all errors are caught and handled appropriately.
"""

import traceback
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable
from enum import Enum

from agent_os.agents.base import BaseAgent
from agent_os.utils.errors import AgentConfigError
from agent_os.utils.circuit_breaker import CircuitBreakerError
from agent_os.utils.cost_tracker import BudgetExceededError
from agent_os.utils.rate_limiter import RateLimitExceeded
from agent_os.utils.retry import MaxRetriesExceeded
from agent_os.utils.timeout import TimeoutError
from agent_os.cli.utils.session import get_agent_os_home


class ExecutionStatus(str, Enum):
    """Execution status values"""
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    BUDGET_EXCEEDED = "budget_exceeded"
    RATE_LIMITED = "rate_limited"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"
    CONFIG_ERROR = "config_error"


class ExecutionResult:
    """Structured execution result with status and metadata"""

    def __init__(
        self,
        status: ExecutionStatus,
        output: Optional[str] = None,
        error: Optional[str] = None,
        error_type: Optional[str] = None,
        suggestions: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        partial_result: Optional[str] = None,
    ):
        self.status = status
        self.output = output
        self.error = error
        self.error_type = error_type
        self.suggestions = suggestions or []
        self.metadata = metadata or {}
        self.partial_result = partial_result
        self.timestamp = datetime.now()

    def is_success(self) -> bool:
        """Check if execution was successful"""
        return self.status == ExecutionStatus.SUCCESS

    def has_partial_result(self) -> bool:
        """Check if there's a partial result available"""
        return self.partial_result is not None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "error_type": self.error_type,
            "suggestions": self.suggestions,
            "metadata": self.metadata,
            "partial_result": self.partial_result,
            "timestamp": self.timestamp.isoformat(),
        }


class ExecutionEngine:
    """
    Robust agent execution engine with comprehensive error handling.

    Features:
    - Catches ALL exceptions (BudgetExceeded, Timeout, CircuitBreaker, etc.)
    - Graceful degradation with partial results
    - Actionable error messages with recovery suggestions
    - Error logging to ~/.agent_os/errors.log
    - Streaming output support (future)
    - No crashes - all errors handled
    """

    def __init__(
        self,
        error_log_path: Optional[Path] = None,
        enable_error_logging: bool = True,
    ):
        """
        Initialize execution engine.

        Args:
            error_log_path: Path to error log file (default: ~/.agent_os/errors.log)
            enable_error_logging: Enable logging errors to file
        """
        self.enable_error_logging = enable_error_logging

        if error_log_path is None:
            error_log_path = get_agent_os_home() / "errors.log"

        self.error_log_path = error_log_path

    def execute(
        self,
        agent: BaseAgent,
        query: str,
        stream: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
    ) -> ExecutionResult:
        """
        Execute agent with comprehensive error handling.

        Args:
            agent: Agent instance to execute
            query: User query to process
            stream: Enable streaming output (future feature)
            stream_callback: Callback for streaming chunks

        Returns:
            ExecutionResult with status, output, and metadata
        """
        if not query or not query.strip():
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                error="Query cannot be empty",
                error_type="ValidationError",
                suggestions=["Provide a non-empty query string"],
            )

        try:
            # Execute agent
            output = agent.run(query)

            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                output=output,
                metadata={
                    "agent_name": agent.name,
                    "model": agent.model_name,
                    "query_length": len(query),
                },
            )

        except BudgetExceededError as e:
            return self._handle_budget_exceeded(agent, query, e)

        except TimeoutError as e:
            return self._handle_timeout(agent, query, e)

        except CircuitBreakerError as e:
            return self._handle_circuit_breaker(agent, query, e)

        except RateLimitExceeded as e:
            return self._handle_rate_limit(agent, query, e)

        except MaxRetriesExceeded as e:
            return self._handle_max_retries(agent, query, e)

        except AgentConfigError as e:
            return self._handle_config_error(agent, query, e)

        except Exception as e:
            return self._handle_unexpected_error(agent, query, e)

    def _handle_budget_exceeded(
        self,
        agent: BaseAgent,
        query: str,
        error: BudgetExceededError,
    ) -> ExecutionResult:
        """Handle budget exceeded error"""
        error_msg = f"Budget exceeded for agent '{agent.name}': {error}"

        suggestions = [
            "Increase the budget limit for this agent",
            "Use a cheaper model (e.g., gpt-4o-mini instead of gpt-4o)",
            "Simplify the query or reduce max_iterations",
            "Check agent metrics to see token usage patterns",
        ]

        self._log_error("BudgetExceededError", error_msg, agent.name, query)

        return ExecutionResult(
            status=ExecutionStatus.BUDGET_EXCEEDED,
            error=error_msg,
            error_type="BudgetExceededError",
            suggestions=suggestions,
            metadata={
                "agent_name": agent.name,
                "model": agent.model_name,
            },
        )

    def _handle_timeout(
        self,
        agent: BaseAgent,
        query: str,
        error: TimeoutError,
    ) -> ExecutionResult:
        """Handle timeout error"""
        error_msg = f"Agent '{agent.name}' execution timed out: {error}"

        suggestions = [
            "Increase max_execution_time parameter",
            "Simplify the query to reduce processing time",
            "Reduce max_iterations to limit execution steps",
            "Check if agent is stuck in a loop",
        ]

        self._log_error("TimeoutError", error_msg, agent.name, query)

        return ExecutionResult(
            status=ExecutionStatus.TIMEOUT,
            error=error_msg,
            error_type="TimeoutError",
            suggestions=suggestions,
            metadata={
                "agent_name": agent.name,
                "max_execution_time": agent.max_execution_time,
            },
        )

    def _handle_circuit_breaker(
        self,
        agent: BaseAgent,
        query: str,
        error: CircuitBreakerError,
    ) -> ExecutionResult:
        """Handle circuit breaker error"""
        error_msg = f"Circuit breaker open for agent '{agent.name}': Too many consecutive failures"

        suggestions = [
            "Wait for circuit breaker to reset (default: 60 seconds)",
            "Check recent error logs to diagnose the underlying issue",
            "Verify tool configurations are correct",
            "Test with a simpler query first",
        ]

        self._log_error("CircuitBreakerError", error_msg, agent.name, query)

        return ExecutionResult(
            status=ExecutionStatus.CIRCUIT_BREAKER_OPEN,
            error=error_msg,
            error_type="CircuitBreakerError",
            suggestions=suggestions,
            metadata={
                "agent_name": agent.name,
            },
        )

    def _handle_rate_limit(
        self,
        agent: BaseAgent,
        query: str,
        error: RateLimitExceeded,
    ) -> ExecutionResult:
        """Handle rate limit exceeded error"""
        error_msg = f"Rate limit exceeded for agent '{agent.name}': {error}"

        suggestions = [
            "Wait before retrying (exponential backoff recommended)",
            "Reduce request frequency",
            "Increase rate limit configuration if possible",
            "Use a different model or API key",
        ]

        self._log_error("RateLimitExceeded", error_msg, agent.name, query)

        return ExecutionResult(
            status=ExecutionStatus.RATE_LIMITED,
            error=error_msg,
            error_type="RateLimitExceeded",
            suggestions=suggestions,
            metadata={
                "agent_name": agent.name,
                "model": agent.model_name,
            },
        )

    def _handle_max_retries(
        self,
        agent: BaseAgent,
        query: str,
        error: MaxRetriesExceeded,
    ) -> ExecutionResult:
        """Handle max retries exceeded error"""
        error_msg = f"Max retries exceeded for agent '{agent.name}': {error}"

        suggestions = [
            "Check error logs for underlying issue causing retries",
            "Verify API keys and credentials are valid",
            "Check network connectivity",
            "Increase retry limit if transient errors are expected",
        ]

        self._log_error("MaxRetriesExceeded", error_msg, agent.name, query)

        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            error=error_msg,
            error_type="MaxRetriesExceeded",
            suggestions=suggestions,
            metadata={
                "agent_name": agent.name,
            },
        )

    def _handle_config_error(
        self,
        agent: BaseAgent,
        query: str,
        error: AgentConfigError,
    ) -> ExecutionResult:
        """Handle agent configuration error"""
        error_msg = f"Configuration error for agent '{agent.name}': {error}"

        suggestions = [
            "Verify agent configuration YAML is valid",
            "Check that all required tools are registered",
            "Ensure model name is correct and supported",
            "Validate all parameters are within acceptable ranges",
        ]

        self._log_error("AgentConfigError", error_msg, agent.name, query)

        return ExecutionResult(
            status=ExecutionStatus.CONFIG_ERROR,
            error=error_msg,
            error_type="AgentConfigError",
            suggestions=suggestions,
            metadata={
                "agent_name": agent.name,
            },
        )

    def _handle_unexpected_error(
        self,
        agent: BaseAgent,
        query: str,
        error: Exception,
    ) -> ExecutionResult:
        """Handle unexpected errors with graceful degradation"""
        error_msg = f"Unexpected error executing agent '{agent.name}': {type(error).__name__}: {error}"

        suggestions = [
            "Check error logs for full traceback",
            "Verify all dependencies are installed",
            "Try with a simpler query to isolate the issue",
            "Report this error if it persists",
        ]

        # Log full traceback for debugging
        full_traceback = traceback.format_exc()
        self._log_error(
            type(error).__name__,
            f"{error_msg}\n\nFull traceback:\n{full_traceback}",
            agent.name,
            query,
        )

        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            error=error_msg,
            error_type=type(error).__name__,
            suggestions=suggestions,
            metadata={
                "agent_name": agent.name,
                "model": agent.model_name,
                "exception_type": type(error).__name__,
            },
        )

    def _log_error(
        self,
        error_type: str,
        error_msg: str,
        agent_name: str,
        query: str,
    ):
        """Log error to file"""
        if not self.enable_error_logging:
            return

        try:
            # Ensure directory exists
            self.error_log_path.parent.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().isoformat()
            log_entry = f"""
{'='*80}
Timestamp: {timestamp}
Error Type: {error_type}
Agent: {agent_name}
Query: {query}
Error: {error_msg}
{'='*80}
"""

            # Append to log file
            with open(self.error_log_path, 'a', encoding='utf-8') as f:
                f.write(log_entry)

        except Exception as log_error:
            # Don't crash if logging fails
            print(f"Warning: Failed to log error: {log_error}")

    def execute_batch(
        self,
        agent: BaseAgent,
        queries: List[str],
    ) -> List[ExecutionResult]:
        """
        Execute multiple queries in batch.

        Args:
            agent: Agent instance
            queries: List of queries to execute

        Returns:
            List of execution results
        """
        return [self.execute(agent, query) for query in queries]


def create_execution_engine(
    error_log_path: Optional[Path] = None,
    enable_error_logging: bool = True,
) -> ExecutionEngine:
    """
    Factory function to create execution engine.

    Args:
        error_log_path: Path to error log file
        enable_error_logging: Enable error logging

    Returns:
        Configured ExecutionEngine
    """
    return ExecutionEngine(
        error_log_path=error_log_path,
        enable_error_logging=enable_error_logging,
    )
