"""
Agent testing utilities

Simple assertion functions for testing agent behavior, tool usage, output quality,
cost, and performance. Designed for use in pytest or standalone scripts.

Example:
    from agent_os import Agent
    from agent_os.testing import AgentTestCase, assert_uses_tool, assert_output_contains

    # Simple assertions
    agent = Agent.researcher()
    assert_uses_tool(agent, "Find papers on RAG", "arxiv_search")
    assert_output_contains(agent, "What is AI?", ["artificial", "intelligence"])

    # Test case class for more structured testing
    class TestResearchAgent(AgentTestCase):
        def setup_agent(self):
            return Agent.researcher()

        def test_uses_arxiv(self):
            self.assert_uses_tool("Find papers on transformers", "arxiv_search")

        def test_output_quality(self):
            self.assert_output_contains("What is RAG?", ["retrieval", "augmented"])
"""

import time
from typing import List, Optional, Union, Any, Dict, Callable
from dataclasses import dataclass, field
from contextlib import contextmanager

# Type hints for agent (avoid circular imports)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from agent_os.agents.base import BaseAgent


@dataclass
class TestResult:
    """Result of a single test assertion"""
    passed: bool
    test_name: str
    query: str
    expected: Any
    actual: Any
    message: str
    duration_ms: float = 0.0
    cost: float = 0.0
    tokens_used: int = 0
    tools_called: List[str] = field(default_factory=list)


class AgentTestError(AssertionError):
    """Raised when an agent test assertion fails"""

    def __init__(self, result: TestResult):
        self.result = result
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        return (
            f"\n{'='*60}\n"
            f"AGENT TEST FAILED: {self.result.test_name}\n"
            f"{'='*60}\n"
            f"Query: {self.result.query}\n"
            f"Expected: {self.result.expected}\n"
            f"Actual: {self.result.actual}\n"
            f"Message: {self.result.message}\n"
            f"Duration: {self.result.duration_ms:.1f}ms\n"
            f"Cost: ${self.result.cost:.4f}\n"
            f"Tools called: {self.result.tools_called}\n"
            f"{'='*60}"
        )


@dataclass
class AgentRunResult:
    """Captured result from running an agent"""
    output: str
    duration_ms: float
    cost: float
    tokens_used: int
    tools_called: List[str]
    raw_response: Any = None


def _run_agent_with_capture(agent: "BaseAgent", query: str) -> AgentRunResult:
    """
    Run agent and capture execution details.

    Args:
        agent: Agent to run
        query: Input query

    Returns:
        AgentRunResult with output and metrics
    """
    start_time = time.perf_counter()

    # Run agent
    output = agent.run(query)

    duration_ms = (time.perf_counter() - start_time) * 1000

    # Extract metrics from agent if available
    cost = 0.0
    tokens_used = 0
    tools_called = []

    # Try to get cost from cost tracker (handle mocks gracefully)
    try:
        if hasattr(agent, 'cost_tracker') and agent.cost_tracker is not None:
            tracker = agent.cost_tracker
            if hasattr(tracker, 'total_cost'):
                cost_value = tracker.total_cost
                # Ensure it's a real number, not a Mock
                if isinstance(cost_value, (int, float)):
                    cost = float(cost_value)
    except Exception:
        cost = 0.0

    # Try to get tool calls from agent's last run (handle mocks gracefully)
    try:
        if hasattr(agent, '_last_tool_calls'):
            calls = agent._last_tool_calls
            # Ensure it's a real list, not a Mock
            if isinstance(calls, list):
                tools_called = calls
    except Exception:
        tools_called = []

    return AgentRunResult(
        output=output,
        duration_ms=duration_ms,
        cost=cost,
        tokens_used=tokens_used,
        tools_called=tools_called
    )


# =============================================================================
# Simple Assertion Functions
# =============================================================================

def assert_uses_tool(
    agent: "BaseAgent",
    query: str,
    expected_tool: str,
    message: str = ""
) -> TestResult:
    """
    Assert that agent uses a specific tool when processing query.

    Args:
        agent: Agent to test
        query: Input query to send to agent
        expected_tool: Tool name that should be used
        message: Optional custom error message

    Returns:
        TestResult on success

    Raises:
        AgentTestError: If tool is not used

    Example:
        assert_uses_tool(agent, "Search for papers on AI", "arxiv_search")
    """
    result = _run_agent_with_capture(agent, query)

    # Check if tool was used (in output or tools_called)
    tool_used = (
        expected_tool in result.tools_called or
        expected_tool.lower() in result.output.lower()
    )

    test_result = TestResult(
        passed=tool_used,
        test_name="assert_uses_tool",
        query=query,
        expected=expected_tool,
        actual=result.tools_called or "No tool tracking available",
        message=message or f"Expected tool '{expected_tool}' to be used",
        duration_ms=result.duration_ms,
        cost=result.cost,
        tokens_used=result.tokens_used,
        tools_called=result.tools_called
    )

    if not tool_used:
        raise AgentTestError(test_result)

    return test_result


def assert_output_contains(
    agent: "BaseAgent",
    query: str,
    keywords: List[str],
    case_sensitive: bool = False,
    message: str = ""
) -> TestResult:
    """
    Assert that agent output contains all specified keywords.

    Args:
        agent: Agent to test
        query: Input query to send to agent
        keywords: List of keywords that must appear in output
        case_sensitive: Whether matching is case-sensitive (default: False)
        message: Optional custom error message

    Returns:
        TestResult on success

    Raises:
        AgentTestError: If any keyword is missing

    Example:
        assert_output_contains(
            agent,
            "What is machine learning?",
            ["algorithm", "data", "model"]
        )
    """
    result = _run_agent_with_capture(agent, query)

    output = result.output if case_sensitive else result.output.lower()
    check_keywords = keywords if case_sensitive else [k.lower() for k in keywords]

    missing = [k for k, orig in zip(check_keywords, keywords) if k not in output]
    all_present = len(missing) == 0

    test_result = TestResult(
        passed=all_present,
        test_name="assert_output_contains",
        query=query,
        expected=keywords,
        actual=f"Missing: {missing}" if missing else "All keywords found",
        message=message or f"Expected output to contain: {keywords}",
        duration_ms=result.duration_ms,
        cost=result.cost,
        tokens_used=result.tokens_used,
        tools_called=result.tools_called
    )

    if not all_present:
        raise AgentTestError(test_result)

    return test_result


def assert_output_not_contains(
    agent: "BaseAgent",
    query: str,
    keywords: List[str],
    case_sensitive: bool = False,
    message: str = ""
) -> TestResult:
    """
    Assert that agent output does NOT contain specified keywords.

    Useful for testing that agents don't leak sensitive info or produce unwanted content.

    Args:
        agent: Agent to test
        query: Input query to send to agent
        keywords: List of keywords that must NOT appear in output
        case_sensitive: Whether matching is case-sensitive (default: False)
        message: Optional custom error message

    Returns:
        TestResult on success

    Raises:
        AgentTestError: If any keyword is found

    Example:
        assert_output_not_contains(agent, "Tell me about users", ["password", "secret"])
    """
    result = _run_agent_with_capture(agent, query)

    output = result.output if case_sensitive else result.output.lower()
    check_keywords = keywords if case_sensitive else [k.lower() for k in keywords]

    found = [orig for k, orig in zip(check_keywords, keywords) if k in output]
    none_found = len(found) == 0

    test_result = TestResult(
        passed=none_found,
        test_name="assert_output_not_contains",
        query=query,
        expected=f"None of: {keywords}",
        actual=f"Found: {found}" if found else "None found (good)",
        message=message or f"Expected output to NOT contain: {keywords}",
        duration_ms=result.duration_ms,
        cost=result.cost,
        tokens_used=result.tokens_used,
        tools_called=result.tools_called
    )

    if not none_found:
        raise AgentTestError(test_result)

    return test_result


def assert_cost_under(
    agent: "BaseAgent",
    query: str,
    max_cost: float,
    message: str = ""
) -> TestResult:
    """
    Assert that agent execution cost is under a limit.

    Args:
        agent: Agent to test
        query: Input query to send to agent
        max_cost: Maximum allowed cost in dollars
        message: Optional custom error message

    Returns:
        TestResult on success

    Raises:
        AgentTestError: If cost exceeds limit

    Example:
        assert_cost_under(agent, "Complex research task", max_cost=0.10)
    """
    # Reset cost tracker if available
    if hasattr(agent, 'cost_tracker') and agent.cost_tracker:
        try:
            initial_cost = agent.cost_tracker.total_cost
        except Exception:
            initial_cost = 0.0
    else:
        initial_cost = 0.0

    result = _run_agent_with_capture(agent, query)

    # Calculate cost for this run
    if hasattr(agent, 'cost_tracker') and agent.cost_tracker:
        try:
            run_cost = agent.cost_tracker.total_cost - initial_cost
        except Exception:
            run_cost = result.cost
    else:
        run_cost = result.cost

    under_limit = run_cost <= max_cost

    test_result = TestResult(
        passed=under_limit,
        test_name="assert_cost_under",
        query=query,
        expected=f"<= ${max_cost:.4f}",
        actual=f"${run_cost:.4f}",
        message=message or f"Cost ${run_cost:.4f} exceeds limit ${max_cost:.4f}",
        duration_ms=result.duration_ms,
        cost=run_cost,
        tokens_used=result.tokens_used,
        tools_called=result.tools_called
    )

    if not under_limit:
        raise AgentTestError(test_result)

    return test_result


def assert_time_under(
    agent: "BaseAgent",
    query: str,
    max_seconds: float,
    message: str = ""
) -> TestResult:
    """
    Assert that agent execution time is under a limit.

    Args:
        agent: Agent to test
        query: Input query to send to agent
        max_seconds: Maximum allowed execution time in seconds
        message: Optional custom error message

    Returns:
        TestResult on success

    Raises:
        AgentTestError: If execution time exceeds limit

    Example:
        assert_time_under(agent, "Quick question", max_seconds=5.0)
    """
    result = _run_agent_with_capture(agent, query)

    duration_seconds = result.duration_ms / 1000
    under_limit = duration_seconds <= max_seconds

    test_result = TestResult(
        passed=under_limit,
        test_name="assert_time_under",
        query=query,
        expected=f"<= {max_seconds:.1f}s",
        actual=f"{duration_seconds:.1f}s",
        message=message or f"Execution time {duration_seconds:.1f}s exceeds limit {max_seconds:.1f}s",
        duration_ms=result.duration_ms,
        cost=result.cost,
        tokens_used=result.tokens_used,
        tools_called=result.tools_called
    )

    if not under_limit:
        raise AgentTestError(test_result)

    return test_result


def assert_output_length(
    agent: "BaseAgent",
    query: str,
    min_length: Optional[int] = None,
    max_length: Optional[int] = None,
    message: str = ""
) -> TestResult:
    """
    Assert that agent output length is within bounds.

    Args:
        agent: Agent to test
        query: Input query to send to agent
        min_length: Minimum output length in characters (optional)
        max_length: Maximum output length in characters (optional)
        message: Optional custom error message

    Returns:
        TestResult on success

    Raises:
        AgentTestError: If output length is out of bounds

    Example:
        assert_output_length(agent, "Summarize in one sentence", max_length=200)
    """
    result = _run_agent_with_capture(agent, query)

    output_length = len(result.output)
    in_bounds = True

    if min_length is not None and output_length < min_length:
        in_bounds = False
    if max_length is not None and output_length > max_length:
        in_bounds = False

    expected = []
    if min_length is not None:
        expected.append(f">= {min_length}")
    if max_length is not None:
        expected.append(f"<= {max_length}")

    test_result = TestResult(
        passed=in_bounds,
        test_name="assert_output_length",
        query=query,
        expected=" and ".join(expected) if expected else "any length",
        actual=f"{output_length} characters",
        message=message or f"Output length {output_length} out of bounds",
        duration_ms=result.duration_ms,
        cost=result.cost,
        tokens_used=result.tokens_used,
        tools_called=result.tools_called
    )

    if not in_bounds:
        raise AgentTestError(test_result)

    return test_result


def assert_no_error(
    agent: "BaseAgent",
    query: str,
    message: str = ""
) -> TestResult:
    """
    Assert that agent executes without raising an exception.

    Args:
        agent: Agent to test
        query: Input query to send to agent
        message: Optional custom error message

    Returns:
        TestResult on success

    Raises:
        AgentTestError: If agent raises an exception

    Example:
        assert_no_error(agent, "Potentially tricky query")
    """
    error = None
    result = None

    start_time = time.perf_counter()
    try:
        output = agent.run(query)
        duration_ms = (time.perf_counter() - start_time) * 1000
        result = AgentRunResult(
            output=output,
            duration_ms=duration_ms,
            cost=0.0,
            tokens_used=0,
            tools_called=[]
        )
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        error = e

    test_result = TestResult(
        passed=error is None,
        test_name="assert_no_error",
        query=query,
        expected="No exception",
        actual=f"Exception: {type(error).__name__}: {error}" if error else "Success",
        message=message or f"Agent raised exception: {error}",
        duration_ms=duration_ms,
        cost=result.cost if result else 0.0,
        tokens_used=result.tokens_used if result else 0,
        tools_called=result.tools_called if result else []
    )

    if error is not None:
        raise AgentTestError(test_result)

    return test_result


def assert_custom(
    agent: "BaseAgent",
    query: str,
    validator: Callable[[str], bool],
    test_name: str = "custom_assertion",
    message: str = ""
) -> TestResult:
    """
    Assert using a custom validation function.

    Args:
        agent: Agent to test
        query: Input query to send to agent
        validator: Function that takes output string and returns True if valid
        test_name: Name for this test (for error reporting)
        message: Optional custom error message

    Returns:
        TestResult on success

    Raises:
        AgentTestError: If validator returns False

    Example:
        def is_json(output):
            try:
                import json
                json.loads(output)
                return True
            except:
                return False

        assert_custom(agent, "Return data as JSON", is_json, "json_format")
    """
    result = _run_agent_with_capture(agent, query)

    try:
        is_valid = validator(result.output)
    except Exception as e:
        is_valid = False
        message = message or f"Validator raised exception: {e}"

    test_result = TestResult(
        passed=is_valid,
        test_name=test_name,
        query=query,
        expected="Validator returns True",
        actual="Valid" if is_valid else "Invalid",
        message=message or "Custom validation failed",
        duration_ms=result.duration_ms,
        cost=result.cost,
        tokens_used=result.tokens_used,
        tools_called=result.tools_called
    )

    if not is_valid:
        raise AgentTestError(test_result)

    return test_result


# =============================================================================
# Test Case Class for Structured Testing
# =============================================================================

class AgentTestCase:
    """
    Base class for structured agent testing.

    Subclass this to create test suites for your agents.

    Example:
        class TestMyAgent(AgentTestCase):
            def setup_agent(self):
                return Agent.researcher()

            def test_uses_wikipedia(self):
                self.assert_uses_tool("Look up Python programming", "wikipedia_search")

            def test_output_quality(self):
                self.assert_output_contains(
                    "What is machine learning?",
                    ["algorithm", "data"]
                )

        # Run tests
        TestMyAgent().run_all()
    """

    def __init__(self):
        self.agent = None
        self.results: List[TestResult] = []

    def setup_agent(self) -> "BaseAgent":
        """
        Override this to create and return the agent to test.

        Returns:
            BaseAgent instance
        """
        raise NotImplementedError("Subclass must implement setup_agent()")

    def setup(self):
        """Called before each test. Override for custom setup."""
        self.agent = self.setup_agent()

    def teardown(self):
        """Called after each test. Override for custom cleanup."""
        pass

    def assert_uses_tool(self, query: str, expected_tool: str, message: str = "") -> TestResult:
        """Assert agent uses a specific tool."""
        return assert_uses_tool(self.agent, query, expected_tool, message)

    def assert_output_contains(
        self,
        query: str,
        keywords: List[str],
        case_sensitive: bool = False,
        message: str = ""
    ) -> TestResult:
        """Assert output contains all keywords."""
        return assert_output_contains(self.agent, query, keywords, case_sensitive, message)

    def assert_output_not_contains(
        self,
        query: str,
        keywords: List[str],
        case_sensitive: bool = False,
        message: str = ""
    ) -> TestResult:
        """Assert output does NOT contain keywords."""
        return assert_output_not_contains(self.agent, query, keywords, case_sensitive, message)

    def assert_cost_under(self, query: str, max_cost: float, message: str = "") -> TestResult:
        """Assert execution cost is under limit."""
        return assert_cost_under(self.agent, query, max_cost, message)

    def assert_time_under(self, query: str, max_seconds: float, message: str = "") -> TestResult:
        """Assert execution time is under limit."""
        return assert_time_under(self.agent, query, max_seconds, message)

    def assert_output_length(
        self,
        query: str,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        message: str = ""
    ) -> TestResult:
        """Assert output length is within bounds."""
        return assert_output_length(self.agent, query, min_length, max_length, message)

    def assert_no_error(self, query: str, message: str = "") -> TestResult:
        """Assert agent executes without error."""
        return assert_no_error(self.agent, query, message)

    def assert_custom(
        self,
        query: str,
        validator: Callable[[str], bool],
        test_name: str = "custom",
        message: str = ""
    ) -> TestResult:
        """Assert using custom validator function."""
        return assert_custom(self.agent, query, validator, test_name, message)

    def run_all(self, verbose: bool = True) -> List[TestResult]:
        """
        Run all test methods (methods starting with 'test_').

        Args:
            verbose: Print results as tests run

        Returns:
            List of TestResult objects
        """
        self.results = []
        test_methods = [m for m in dir(self) if m.startswith('test_') and callable(getattr(self, m))]

        passed = 0
        failed = 0

        if verbose:
            print(f"\n{'='*60}")
            print(f"Running {len(test_methods)} tests for {self.__class__.__name__}")
            print(f"{'='*60}\n")

        for method_name in test_methods:
            self.setup()

            try:
                method = getattr(self, method_name)
                result = method()

                if result and isinstance(result, TestResult):
                    self.results.append(result)

                passed += 1
                if verbose:
                    print(f"  PASS: {method_name}")

            except AgentTestError as e:
                self.results.append(e.result)
                failed += 1
                if verbose:
                    print(f"  FAIL: {method_name}")
                    print(f"        {e.result.message}")

            except Exception as e:
                failed += 1
                if verbose:
                    print(f"  ERROR: {method_name}")
                    print(f"         {type(e).__name__}: {e}")

            finally:
                self.teardown()

        if verbose:
            print(f"\n{'='*60}")
            print(f"Results: {passed} passed, {failed} failed")
            print(f"{'='*60}\n")

        return self.results


# =============================================================================
# Convenience Context Manager
# =============================================================================

@contextmanager
def agent_test_context(agent: "BaseAgent"):
    """
    Context manager for testing an agent.

    Example:
        with agent_test_context(agent) as test:
            test.assert_uses_tool("query", "tool_name")
            test.assert_output_contains("query", ["keyword"])
    """
    class TestContext:
        def __init__(self, agent):
            self.agent = agent

        def assert_uses_tool(self, query, expected_tool, message=""):
            return assert_uses_tool(self.agent, query, expected_tool, message)

        def assert_output_contains(self, query, keywords, case_sensitive=False, message=""):
            return assert_output_contains(self.agent, query, keywords, case_sensitive, message)

        def assert_output_not_contains(self, query, keywords, case_sensitive=False, message=""):
            return assert_output_not_contains(self.agent, query, keywords, case_sensitive, message)

        def assert_cost_under(self, query, max_cost, message=""):
            return assert_cost_under(self.agent, query, max_cost, message)

        def assert_time_under(self, query, max_seconds, message=""):
            return assert_time_under(self.agent, query, max_seconds, message)

        def assert_output_length(self, query, min_length=None, max_length=None, message=""):
            return assert_output_length(self.agent, query, min_length, max_length, message)

        def assert_no_error(self, query, message=""):
            return assert_no_error(self.agent, query, message)

        def assert_custom(self, query, validator, test_name="custom", message=""):
            return assert_custom(self.agent, query, validator, test_name, message)

    yield TestContext(agent)


# =============================================================================
# Export all public functions
# =============================================================================

__all__ = [
    # Assertion functions
    "assert_uses_tool",
    "assert_output_contains",
    "assert_output_not_contains",
    "assert_cost_under",
    "assert_time_under",
    "assert_output_length",
    "assert_no_error",
    "assert_custom",
    # Classes
    "AgentTestCase",
    "AgentTestError",
    "TestResult",
    "AgentRunResult",
    # Context manager
    "agent_test_context",
]
