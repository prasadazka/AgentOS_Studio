"""GCP Cloud Logging tools - log reading, error analysis"""

import subprocess
import shutil
import json
import re
import sys
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import ToolExecutionError, ErrorCode
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Type-Safe Models
# =============================================================================

class LogEntry(BaseModel):
    """Single log entry"""
    timestamp: Optional[str] = None
    severity: Optional[str] = None
    message: str = ""
    resource: Optional[Dict[str, Any]] = None
    labels: Optional[Dict[str, str]] = None


class LogQueryResult(BaseModel):
    """Result of log query"""
    success: bool
    project_id: Optional[str] = None
    query_filter: Optional[str] = None
    entries_count: int = 0
    entries: List[Dict[str, Any]] = Field(default_factory=list)
    has_more: bool = False
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class ErrorAnalysisResult(BaseModel):
    """Result of error log analysis"""
    success: bool
    project_id: Optional[str] = None
    total_errors: int = 0
    error_categories: Dict[str, int] = Field(default_factory=dict)
    top_errors: List[Dict[str, Any]] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    time_range: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Error Pattern Definitions
# =============================================================================

ERROR_PATTERNS = {
    "connection": {
        "patterns": [
            r"connection refused",
            r"connection timed out",
            r"connection reset",
            r"ECONNREFUSED",
            r"ETIMEDOUT",
            r"network unreachable"
        ],
        "category": "Network/Connection",
        "suggestion": "Check network connectivity, firewall rules, and service availability"
    },
    "memory": {
        "patterns": [
            r"out of memory",
            r"OOMKilled",
            r"memory limit exceeded",
            r"MemoryError",
            r"heap out of memory"
        ],
        "category": "Memory",
        "suggestion": "Increase memory allocation or optimize memory usage"
    },
    "permission": {
        "patterns": [
            r"permission denied",
            r"access denied",
            r"PERMISSION_DENIED",
            r"403 Forbidden",
            r"unauthorized",
            r"IAM"
        ],
        "category": "Permission/IAM",
        "suggestion": "Check IAM roles and permissions for the service account"
    },
    "config": {
        "patterns": [
            r"missing.*config",
            r"invalid.*config",
            r"environment variable.*not set",
            r"KeyError",
            r"configuration error"
        ],
        "category": "Configuration",
        "suggestion": "Verify environment variables and configuration settings"
    },
    "database": {
        "patterns": [
            r"database.*error",
            r"sql.*error",
            r"connection.*database",
            r"deadlock",
            r"query timeout"
        ],
        "category": "Database",
        "suggestion": "Check database connection string and credentials"
    },
    "dependency": {
        "patterns": [
            r"module not found",
            r"import error",
            r"no such file",
            r"package.*not found",
            r"ModuleNotFoundError"
        ],
        "category": "Dependencies",
        "suggestion": "Verify all dependencies are installed in the container"
    },
    "timeout": {
        "patterns": [
            r"request timeout",
            r"deadline exceeded",
            r"TimeoutError",
            r"504 Gateway Timeout"
        ],
        "category": "Timeout",
        "suggestion": "Increase timeout settings or optimize request handling"
    },
    "crash": {
        "patterns": [
            r"segmentation fault",
            r"core dumped",
            r"fatal error",
            r"panic:",
            r"SIGKILL",
            r"SIGSEGV"
        ],
        "category": "Crash",
        "suggestion": "Check for bugs in application code or native dependencies"
    },
    "startup": {
        "patterns": [
            r"failed to start",
            r"container failed",
            r"health check failed",
            r"readiness probe failed",
            r"port.*not listening"
        ],
        "category": "Startup",
        "suggestion": "Verify startup command, port binding, and health check endpoints"
    }
}


def categorize_error(message: str) -> Optional[Dict[str, str]]:
    """Categorize error message by pattern"""
    message_lower = message.lower()

    for error_type, info in ERROR_PATTERNS.items():
        for pattern in info["patterns"]:
            if re.search(pattern, message_lower, re.IGNORECASE):
                return {
                    "type": error_type,
                    "category": info["category"],
                    "suggestion": info["suggestion"]
                }

    return None


# =============================================================================
# GCP Logging Tool
# =============================================================================

class GCPLoggingTool(BaseTool):
    """Read logs from GCP Cloud Logging

    Features:
    - Query logs with filters
    - Filter by severity (ERROR, WARNING, INFO, etc.)
    - Filter by resource (Cloud Run, GCE, etc.)
    - Time range filtering
    - Limit and pagination
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="gcp_logging",
                description="Read logs from GCP Cloud Logging with filters",
                category="gcp",
                tags=["gcp", "logging", "monitoring", "debugging"],
                requires_auth=True
            )
        )
        self._gcloud_path = shutil.which("gcloud")

    def _run_gcloud(self, args: List[str], timeout: int = 120) -> subprocess.CompletedProcess:
        """Run gcloud command with Windows compatibility"""
        cmd = [self._gcloud_path or "gcloud"] + args
        if sys.platform == "win32":
            # Quote paths that contain spaces for Windows shell
            cmd_str = " ".join(f'"{c}"' if " " in c else c for c in cmd)
            return subprocess.run(cmd_str, shell=True, capture_output=True, text=True, timeout=timeout)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def _get_current_project(self) -> Optional[str]:
        """Get current GCP project"""
        try:
            result = self._run_gcloud(["config", "get-value", "project"], timeout=30)
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def _build_filter(
        self,
        severity: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_name: Optional[str] = None,
        text_filter: Optional[str] = None,
        hours_ago: int = 1
    ) -> str:
        """Build log filter string"""
        filters = []

        # Time filter
        start_time = datetime.utcnow() - timedelta(hours=hours_ago)
        filters.append(f'timestamp >= "{start_time.isoformat()}Z"')

        # Severity filter
        if severity:
            sev_upper = severity.upper()
            if sev_upper in ["ERROR", "WARNING", "INFO", "DEBUG", "CRITICAL"]:
                if sev_upper == "ERROR":
                    filters.append('severity >= "ERROR"')
                else:
                    filters.append(f'severity = "{sev_upper}"')

        # Resource type filter
        if resource_type:
            filters.append(f'resource.type = "{resource_type}"')

        # Resource name filter (for Cloud Run services, etc.)
        if resource_name:
            filters.append(f'resource.labels.service_name = "{resource_name}"')

        # Text search filter
        if text_filter:
            # Escape quotes in filter
            escaped = text_filter.replace('"', '\\"')
            filters.append(f'textPayload:"{escaped}" OR jsonPayload.message:"{escaped}"')

        return " AND ".join(filters)

    def _execute(
        self,
        project_id: Optional[str] = None,
        severity: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_name: Optional[str] = None,
        text_filter: Optional[str] = None,
        custom_filter: Optional[str] = None,
        hours_ago: int = 1,
        limit: int = 100
    ) -> str:
        """Query GCP logs

        Args:
            project_id: GCP project ID
            severity: Log severity (ERROR, WARNING, INFO, DEBUG)
            resource_type: Resource type (e.g., cloud_run_revision, gce_instance)
            resource_name: Resource name (e.g., service name for Cloud Run)
            text_filter: Text to search in log messages
            custom_filter: Custom filter string (overrides other filters)
            hours_ago: How many hours back to search (default: 1)
            limit: Maximum entries to return (default: 100)

        Returns:
            JSON with log entries
        """
        try:
            if not self._gcloud_path:
                return LogQueryResult(
                    success=False,
                    error="gcloud CLI not installed",
                    error_code=ErrorCode.TOOL_DEPENDENCY_MISSING.value
                ).to_json()

            project = project_id or self._get_current_project()
            if not project:
                return LogQueryResult(
                    success=False,
                    error="No GCP project specified",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

            # Build filter
            if custom_filter:
                log_filter = custom_filter
            else:
                log_filter = self._build_filter(
                    severity=severity,
                    resource_type=resource_type,
                    resource_name=resource_name,
                    text_filter=text_filter,
                    hours_ago=hours_ago
                )

            # Execute query
            result = self._run_gcloud([
                "logging", "read", log_filter,
                "--project", project,
                "--limit", str(min(limit, 500)),  # Cap at 500
                "--format", "json"
            ])

            if result.returncode != 0:
                return LogQueryResult(
                    success=False,
                    project_id=project,
                    query_filter=log_filter,
                    error=result.stderr.strip(),
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                ).to_json()

            # Parse results
            try:
                entries = json.loads(result.stdout) if result.stdout else []
            except json.JSONDecodeError:
                entries = []

            # Format entries
            formatted_entries = []
            for entry in entries[:limit]:
                formatted = {
                    "timestamp": entry.get("timestamp"),
                    "severity": entry.get("severity"),
                    "message": entry.get("textPayload") or
                              entry.get("jsonPayload", {}).get("message") or
                              str(entry.get("jsonPayload", {}))[:500]
                }

                # Add resource info if present
                resource = entry.get("resource", {})
                if resource:
                    formatted["resource_type"] = resource.get("type")
                    formatted["resource_labels"] = resource.get("labels", {})

                formatted_entries.append(formatted)

            logger.info(f"Retrieved {len(formatted_entries)} log entries", extra={
                "project": project,
                "filter": log_filter[:100]
            })

            return LogQueryResult(
                success=True,
                project_id=project,
                query_filter=log_filter,
                entries_count=len(formatted_entries),
                entries=formatted_entries,
                has_more=len(entries) >= limit
            ).to_json()

        except subprocess.TimeoutExpired:
            return LogQueryResult(
                success=False,
                error="Query timed out",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()

        except Exception as e:
            logger.error(f"Log query failed: {e}", exc_info=True)
            return LogQueryResult(
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


# =============================================================================
# GCP Error Analyzer Tool
# =============================================================================

class GCPErrorAnalyzerTool(BaseTool):
    """Analyze error logs and provide suggestions

    Features:
    - Categorize errors by type
    - Identify most common errors
    - Provide fix suggestions
    - Summarize error patterns
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="gcp_error_analyzer",
                description="Analyze GCP error logs and suggest fixes",
                category="gcp",
                tags=["gcp", "logging", "debugging", "analysis"],
                requires_auth=True
            )
        )
        self.logging_tool = GCPLoggingTool()

    def _execute(
        self,
        project_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_name: Optional[str] = None,
        hours_ago: int = 24,
        limit: int = 200
    ) -> str:
        """Analyze error logs

        Args:
            project_id: GCP project ID
            resource_type: Filter by resource type
            resource_name: Filter by resource name (e.g., Cloud Run service)
            hours_ago: How many hours back to analyze (default: 24)
            limit: Maximum entries to analyze (default: 200)

        Returns:
            JSON with error analysis
        """
        try:
            # Fetch error logs
            execute_result = self.logging_tool.execute(
                project_id=project_id,
                severity="ERROR",
                resource_type=resource_type,
                resource_name=resource_name,
                hours_ago=hours_ago,
                limit=limit
            )

            # execute() returns {"success": True, "result": "<json_string>"}
            # The result is the JSON string from _execute()
            log_result = json.loads(execute_result["result"])

            if not log_result.get("success"):
                return ErrorAnalysisResult(
                    success=False,
                    error=f"Failed to fetch logs: {log_result.get('error')}",
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                ).to_json()

            entries = log_result.get("entries", [])

            if not entries:
                return ErrorAnalysisResult(
                    success=True,
                    project_id=project_id,
                    total_errors=0,
                    suggestions=["No errors found in the specified time range"],
                    time_range=f"Last {hours_ago} hours"
                ).to_json()

            # Analyze errors
            error_categories: Dict[str, int] = {}
            error_messages: Dict[str, Dict[str, Any]] = {}
            all_suggestions = set()

            for entry in entries:
                message = entry.get("message", "")

                # Categorize error
                categorization = categorize_error(message)

                if categorization:
                    category = categorization["category"]
                    error_categories[category] = error_categories.get(category, 0) + 1
                    all_suggestions.add(categorization["suggestion"])
                else:
                    error_categories["Uncategorized"] = error_categories.get("Uncategorized", 0) + 1

                # Track unique error messages
                msg_key = message[:200]  # Truncate for grouping
                if msg_key not in error_messages:
                    error_messages[msg_key] = {
                        "message": message[:500],
                        "count": 0,
                        "first_seen": entry.get("timestamp"),
                        "last_seen": entry.get("timestamp"),
                        "category": categorization["category"] if categorization else "Uncategorized"
                    }
                error_messages[msg_key]["count"] += 1
                error_messages[msg_key]["last_seen"] = entry.get("timestamp")

            # Sort by count
            top_errors = sorted(
                error_messages.values(),
                key=lambda x: x["count"],
                reverse=True
            )[:10]

            # Build suggestions
            suggestions = list(all_suggestions)

            # Add general suggestions based on patterns
            if error_categories.get("Startup", 0) > 0:
                suggestions.insert(0, "CRITICAL: Service failing to start - check startup logs first")

            if error_categories.get("Memory", 0) > 0:
                suggestions.insert(0, "CRITICAL: Memory issues detected - consider increasing memory allocation")

            if len(top_errors) > 0 and top_errors[0]["count"] > 10:
                suggestions.insert(0, f"HIGH FREQUENCY: '{top_errors[0]['category']}' errors occurring {top_errors[0]['count']} times")

            logger.info(f"Error analysis complete: {len(entries)} errors analyzed", extra={
                "total_errors": len(entries),
                "categories": list(error_categories.keys())
            })

            return ErrorAnalysisResult(
                success=True,
                project_id=project_id,
                total_errors=len(entries),
                error_categories=error_categories,
                top_errors=top_errors,
                suggestions=suggestions[:10],
                time_range=f"Last {hours_ago} hours"
            ).to_json()

        except Exception as e:
            logger.error(f"Error analysis failed: {e}", exc_info=True)
            return ErrorAnalysisResult(
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


# =============================================================================
# Cloud Run Log Tool (Convenience Wrapper)
# =============================================================================

class CloudRunLogTool(BaseTool):
    """Read logs specifically for Cloud Run services

    Convenience wrapper around GCPLoggingTool with Cloud Run defaults
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="cloud_run_logs",
                description="Read logs from a specific Cloud Run service",
                category="gcp",
                tags=["gcp", "cloud-run", "logging", "debugging"],
                requires_auth=True
            )
        )
        self.logging_tool = GCPLoggingTool()

    def _execute(
        self,
        service_name: str,
        project_id: Optional[str] = None,
        region: str = "us-central1",
        severity: Optional[str] = None,
        hours_ago: int = 1,
        limit: int = 100
    ) -> str:
        """Read Cloud Run service logs

        Args:
            service_name: Cloud Run service name
            project_id: GCP project ID
            region: Cloud Run region
            severity: Log severity filter
            hours_ago: How many hours back
            limit: Maximum entries

        Returns:
            JSON with log entries
        """
        # Call underlying logging tool
        execute_result = self.logging_tool.execute(
            project_id=project_id,
            resource_type="cloud_run_revision",
            resource_name=service_name,
            severity=severity,
            hours_ago=hours_ago,
            limit=limit
        )
        # Return the JSON string result
        return execute_result["result"]
