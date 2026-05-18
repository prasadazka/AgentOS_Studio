"""Workflow Tracking Tools - Monitor multi-agent execution"""

import time
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Type-Safe Models
# =============================================================================

class ProgressEvent(BaseModel):
    """Progress event for logging"""
    timestamp: str
    phase: str
    agent: Optional[str] = None
    action: str  # "start", "progress", "complete", "error"
    message: str
    duration: Optional[float] = None


class ExecutionMetrics(BaseModel):
    """Execution metrics for an agent or phase"""
    name: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration: Optional[float] = None
    success: bool = False
    error: Optional[str] = None


# =============================================================================
# Progress Logger Tool
# =============================================================================

class ProgressLoggerTool(BaseTool):
    """Log progress events to console with formatted output

    Features:
    - Clean console formatting
    - Phase headers and separators
    - Agent execution indicators (→, ✓, ✗)
    - Execution duration display
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="progress_logger",
                description="Log workflow progress events with formatted console output",
                category="monitoring",
                tags=["logging", "progress", "console"]
            )
        )
        self._events: List[ProgressEvent] = []

    def _execute(
        self,
        phase: str,
        action: str,
        message: str,
        agent: Optional[str] = None,
        duration: Optional[float] = None
    ) -> str:
        """Log a progress event

        Args:
            phase: Current workflow phase (e.g., "Phase 1/5")
            action: Event type ("start", "progress", "complete", "error")
            message: Progress message to display
            agent: Optional agent name
            duration: Optional duration in seconds

        Returns:
            Formatted log message
        """
        event = ProgressEvent(
            timestamp=datetime.now().isoformat(),
            phase=phase,
            agent=agent,
            action=action,
            message=message,
            duration=duration
        )

        self._events.append(event)

        # Format output based on action (ASCII for Windows compatibility)
        if action == "start":
            symbol = ">"
        elif action == "complete":
            symbol = "[OK]"
        elif action == "error":
            symbol = "[ERR]"
        else:
            symbol = "*"

        # Build output message
        output_parts = []

        if agent:
            output_parts.append(f"  {symbol} {agent}")
        else:
            output_parts.append(f"  {symbol} {message}")

        if duration is not None and duration > 0.1:
            output_parts.append(f"({duration:.1f}s)")

        if action == "complete" and agent and message:
            output_parts.append(f"- {message}")

        output = " ".join(output_parts)

        # Print to console
        print(output)

        return output

    def get_events(self) -> List[Dict[str, Any]]:
        """Get all logged events"""
        return [event.model_dump() for event in self._events]


# =============================================================================
# Execution Timer Tool
# =============================================================================

class ExecutionTimerTool(BaseTool):
    """Track execution timing for agents and phases

    Features:
    - Start/stop timer for operations
    - Calculate durations
    - Track multiple concurrent timers
    - Generate timing reports
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="execution_timer",
                description="Track execution timing for workflow operations",
                category="monitoring",
                tags=["timing", "performance", "metrics"]
            )
        )
        self._timers: Dict[str, float] = {}
        self._metrics: Dict[str, ExecutionMetrics] = {}

    def _execute(
        self,
        action: str,
        name: str,
        success: Optional[bool] = None,
        error: Optional[str] = None
    ) -> str:
        """Manage execution timer

        Args:
            action: "start", "stop", "get", "report"
            name: Identifier for the timer (e.g., "code_analyzer", "phase_1")
            success: Whether operation succeeded (for "stop" action)
            error: Error message if operation failed

        Returns:
            JSON with timing information
        """
        action = action.lower()

        if action == "start":
            self._timers[name] = time.time()
            self._metrics[name] = ExecutionMetrics(
                name=name,
                start_time=self._timers[name]
            )
            return f"Started timer for {name}"

        elif action == "stop":
            if name not in self._timers:
                return f"No active timer for {name}"

            end_time = time.time()
            duration = end_time - self._timers[name]

            self._metrics[name].end_time = end_time
            self._metrics[name].duration = duration
            self._metrics[name].success = success if success is not None else True
            self._metrics[name].error = error

            del self._timers[name]

            return f"Stopped timer for {name}: {duration:.1f}s"

        elif action == "get":
            if name not in self._metrics:
                return f"No metrics for {name}"

            metric = self._metrics[name]
            if metric.duration is not None:
                return f"{name}: {metric.duration:.1f}s (success: {metric.success})"
            else:
                elapsed = time.time() - metric.start_time if metric.start_time else 0
                return f"{name}: {elapsed:.1f}s (running)"

        elif action == "report":
            if not self._metrics:
                return "No metrics available"

            lines = ["Execution Metrics:", ""]
            total_duration = 0.0

            for name, metric in self._metrics.items():
                if metric.duration:
                    status = "✓" if metric.success else "✗"
                    lines.append(f"  {status} {name}: {metric.duration:.1f}s")
                    total_duration += metric.duration
                else:
                    lines.append(f"  → {name}: running...")

            lines.append("")
            lines.append(f"Total: {total_duration:.1f}s")

            return "\n".join(lines)

        else:
            return f"Unknown action: {action}"

    def get_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get all execution metrics"""
        return {
            name: metric.model_dump()
            for name, metric in self._metrics.items()
        }


# =============================================================================
# Phase Monitor Tool
# =============================================================================

class PhaseMonitorTool(BaseTool):
    """Monitor workflow phases and detect issues

    Features:
    - Track phase progression
    - Detect stuck phases (timeout detection)
    - Monitor agent health
    - Alert on anomalies
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="phase_monitor",
                description="Monitor workflow phases and detect stuck operations",
                category="monitoring",
                tags=["monitoring", "alerting", "health"]
            )
        )
        self._phase_start_times: Dict[str, float] = {}
        self._current_phase: Optional[str] = None

    def _execute(
        self,
        action: str,
        phase: Optional[str] = None,
        timeout: float = 300.0  # 5 minutes default
    ) -> str:
        """Monitor phase execution

        Args:
            action: "start", "end", "check", "status"
            phase: Phase identifier
            timeout: Maximum allowed duration in seconds

        Returns:
            Status message or alert
        """
        action = action.lower()

        if action == "start":
            if not phase:
                return "Phase name required for 'start' action"

            self._current_phase = phase
            self._phase_start_times[phase] = time.time()
            return f"Started monitoring phase: {phase}"

        elif action == "end":
            if not phase:
                return "Phase name required for 'end' action"

            if phase not in self._phase_start_times:
                return f"Phase {phase} was not started"

            duration = time.time() - self._phase_start_times[phase]
            del self._phase_start_times[phase]

            if phase == self._current_phase:
                self._current_phase = None

            return f"Phase {phase} completed in {duration:.1f}s"

        elif action == "check":
            if not self._current_phase:
                return "No active phase"

            if self._current_phase not in self._phase_start_times:
                return "Current phase timing data missing"

            elapsed = time.time() - self._phase_start_times[self._current_phase]

            if elapsed > timeout:
                return f"⚠ ALERT: Phase {self._current_phase} stuck ({elapsed:.0f}s > {timeout:.0f}s timeout)"

            return f"Phase {self._current_phase} running normally ({elapsed:.1f}s)"

        elif action == "status":
            if not self._current_phase:
                return "No active phase"

            elapsed = time.time() - self._phase_start_times.get(self._current_phase, time.time())
            return f"Current phase: {self._current_phase} ({elapsed:.1f}s)"

        else:
            return f"Unknown action: {action}"


# =============================================================================
# Console Formatter Tool
# =============================================================================

class ConsoleFormatterTool(BaseTool):
    """Format console output with headers, separators, and styling

    Features:
    - Section headers with separators
    - Indented content
    - Status indicators
    - Consistent spacing
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="console_formatter",
                description="Format console output with professional styling",
                category="utilities",
                tags=["formatting", "console", "display"]
            )
        )

    def _execute(
        self,
        format_type: str,
        content: str,
        width: int = 70
    ) -> str:
        """Format console output

        Args:
            format_type: "header", "section", "list", "separator"
            content: Content to format
            width: Output width in characters

        Returns:
            Formatted string
        """
        format_type = format_type.lower()

        if format_type == "header":
            separator = "=" * width
            lines = [
                "",
                separator,
                f"  {content}",
                separator,
                ""
            ]
            output = "\n".join(lines)

        elif format_type == "section":
            lines = [
                "",
                f"[{content}]",
                ""
            ]
            output = "\n".join(lines)

        elif format_type == "separator":
            output = "-" * width

        elif format_type == "list":
            # Content should be newline-separated list items
            items = content.split("\n")
            formatted_items = [f"  - {item}" for item in items if item.strip()]
            output = "\n".join(formatted_items)

        else:
            output = content

        # Print to console
        print(output)

        return output


# =============================================================================
# Status Reporter Tool
# =============================================================================

class StatusReporterTool(BaseTool):
    """Generate execution status reports and summaries

    Features:
    - Real-time status updates
    - Execution summaries
    - Performance metrics
    - Timeline visualization
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="status_reporter",
                description="Generate workflow execution status reports",
                category="reporting",
                tags=["reporting", "status", "summary"]
            )
        )

    def _execute(
        self,
        report_type: str,
        data: Dict[str, Any]
    ) -> str:
        """Generate status report

        Args:
            report_type: "summary", "timeline", "metrics", "errors"
            data: Report data (phases, agents, timings, etc.)

        Returns:
            Formatted report
        """
        report_type = report_type.lower()

        if report_type == "summary":
            return self._generate_summary(data)
        elif report_type == "timeline":
            return self._generate_timeline(data)
        elif report_type == "metrics":
            return self._generate_metrics(data)
        elif report_type == "errors":
            return self._generate_error_report(data)
        else:
            return f"Unknown report type: {report_type}"

    def _generate_summary(self, data: Dict[str, Any]) -> str:
        """Generate execution summary"""
        lines = [
            "",
            "Execution Summary:",
            "=" * 70,
            ""
        ]

        if "total_duration" in data:
            lines.append(f"Total Duration: {data['total_duration']:.1f}s")

        if "agents_executed" in data:
            lines.append(f"Agents Executed: {data['agents_executed']}")

        if "phases_completed" in data:
            lines.append(f"Phases Completed: {data['phases_completed']}")

        if "success_rate" in data:
            lines.append(f"Success Rate: {data['success_rate']:.1f}%")

        lines.append("")

        return "\n".join(lines)

    def _generate_timeline(self, data: Dict[str, Any]) -> str:
        """Generate execution timeline"""
        lines = [
            "",
            "Timeline:",
            "-" * 70,
            ""
        ]

        if "events" in data:
            for event in data["events"]:
                agent = event.get("agent", "System")
                duration = event.get("duration", 0)
                message = event.get("message", "")

                if duration > 0:
                    lines.append(f"  {agent}: {duration:.1f}s - {message}")
                else:
                    lines.append(f"  {agent}: {message}")

        lines.append("")

        return "\n".join(lines)

    def _generate_metrics(self, data: Dict[str, Any]) -> str:
        """Generate performance metrics"""
        lines = [
            "",
            "Performance Metrics:",
            "-" * 70,
            ""
        ]

        if "metrics" in data:
            for name, metric in data["metrics"].items():
                duration = metric.get("duration", 0)
                success = metric.get("success", False)
                status = "✓" if success else "✗"

                lines.append(f"  {status} {name}: {duration:.1f}s")

        lines.append("")

        return "\n".join(lines)

    def _generate_error_report(self, data: Dict[str, Any]) -> str:
        """Generate error report"""
        lines = [
            "",
            "Errors:",
            "-" * 70,
            ""
        ]

        if "errors" in data and data["errors"]:
            for error in data["errors"]:
                lines.append(f"  ✗ {error}")
        else:
            lines.append("  No errors")

        lines.append("")

        return "\n".join(lines)
