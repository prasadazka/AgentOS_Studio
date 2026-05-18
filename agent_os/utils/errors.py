"""Production-grade exception hierarchy for Agent_OS

This module provides a comprehensive error handling system with:
- Structured error codes for programmatic handling
- Rich error context (details, original exception)
- Proper exception chaining
- Type-safe error responses
"""

from typing import Optional, Dict, Any
from enum import Enum


class ErrorCode(str, Enum):
    """Standardized error codes for Agent_OS"""

    # Tool Execution Errors (1xxx)
    TOOL_EXECUTION_FAILED = "TOOL_1000"
    TOOL_NOT_FOUND = "TOOL_1001"
    TOOL_VALIDATION_ERROR = "TOOL_1002"
    TOOL_TIMEOUT = "TOOL_1003"
    TOOL_RATE_LIMITED = "TOOL_1004"
    TOOL_DEPENDENCY_MISSING = "TOOL_1005"

    # Network Errors (2xxx)
    NETWORK_TIMEOUT = "NET_2000"
    NETWORK_CONNECTION_ERROR = "NET_2001"
    NETWORK_DNS_ERROR = "NET_2002"
    HTTP_ERROR = "NET_2100"
    HTTP_400 = "NET_2400"
    HTTP_401 = "NET_2401"
    HTTP_403 = "NET_2403"
    HTTP_404 = "NET_2404"
    HTTP_429 = "NET_2429"
    HTTP_500 = "NET_2500"
    HTTP_502 = "NET_2502"
    HTTP_503 = "NET_2503"

    # Database Errors (3xxx)
    DB_CONNECTION_ERROR = "DB_3000"
    DB_QUERY_ERROR = "DB_3001"
    DB_CONSTRAINT_VIOLATION = "DB_3002"
    DB_TRANSACTION_ERROR = "DB_3003"

    # Security Errors (4xxx)
    SECURITY_VALIDATION_FAILED = "SEC_4000"
    SECURITY_PII_DETECTED = "SEC_4001"
    SECURITY_SQL_INJECTION = "SEC_4002"
    SECURITY_XSS_DETECTED = "SEC_4003"
    SECURITY_UNAUTHORIZED = "SEC_4004"

    # Resource Errors (5xxx)
    RESOURCE_NOT_FOUND = "RES_5000"
    RESOURCE_EXHAUSTED = "RES_5001"
    RESOURCE_LOCKED = "RES_5002"
    FILE_NOT_FOUND = "RES_5100"
    FILE_PERMISSION_ERROR = "RES_5101"
    FILE_TOO_LARGE = "RES_5102"

    # Configuration Errors (6xxx)
    CONFIG_INVALID = "CFG_6000"
    CONFIG_MISSING_KEY = "CFG_6001"
    CONFIG_TYPE_ERROR = "CFG_6002"

    # Agent Errors (7xxx)
    AGENT_INITIALIZATION_ERROR = "AGT_7000"
    AGENT_EXECUTION_ERROR = "AGT_7001"

    # Workflow Errors (8xxx)
    WORKFLOW_EXECUTION_ERROR = "WF_8000"
    WORKFLOW_STATE_ERROR = "WF_8001"

    # Unknown/Generic
    UNKNOWN_ERROR = "UNKNOWN"


class AgentOSError(Exception):
    """
    Base exception for Agent_OS with structured error information

    Attributes:
        message: Human-readable error message
        error_code: Standardized error code (ErrorCode enum)
        details: Additional structured error context
        original_error: Original exception if this is a wrapped error
    """

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None
    ):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.original_error = original_error

        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for serialization"""
        result = {
            "error": self.message,
            "error_code": self.error_code.value,
            "error_type": self.__class__.__name__,
            "details": self.details
        }

        if self.original_error:
            result["original_error"] = {
                "type": type(self.original_error).__name__,
                "message": str(self.original_error)
            }

        return result

    def __str__(self) -> str:
        parts = [f"[{self.error_code.value}] {self.message}"]
        if self.details:
            parts.append(f"Details: {self.details}")
        if self.original_error:
            parts.append(f"Caused by: {type(self.original_error).__name__}: {self.original_error}")
        return " | ".join(parts)


# ============================================================================
# Tool Errors
# ============================================================================

class ToolError(AgentOSError):
    """Base class for tool-related errors"""
    pass


class ToolExecutionError(ToolError):
    """Raised when a tool execution fails"""

    def __init__(
        self,
        message: str,
        tool_name: Optional[str] = None,
        error_code: ErrorCode = ErrorCode.TOOL_EXECUTION_FAILED,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None
    ):
        if tool_name and details:
            details["tool_name"] = tool_name
        elif tool_name:
            details = {"tool_name": tool_name}

        super().__init__(message, error_code, details, original_error)


class ToolValidationError(ToolError):
    """Raised when tool input validation fails"""

    def __init__(
        self,
        message: str,
        field_name: Optional[str] = None,
        expected_type: Optional[str] = None,
        actual_value: Optional[Any] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        if field_name:
            details["field_name"] = field_name
        if expected_type:
            details["expected_type"] = expected_type
        if actual_value is not None:
            details["actual_value"] = str(actual_value)[:100]  # Truncate large values

        super().__init__(
            message,
            error_code=ErrorCode.TOOL_VALIDATION_ERROR,
            details=details
        )


class ToolTimeoutError(ToolError):
    """Raised when a tool operation times out"""

    def __init__(
        self,
        message: str,
        timeout_seconds: Optional[float] = None,
        tool_name: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        if timeout_seconds:
            details["timeout_seconds"] = timeout_seconds
        if tool_name:
            details["tool_name"] = tool_name

        super().__init__(
            message,
            error_code=ErrorCode.TOOL_TIMEOUT,
            details=details
        )


class ToolDependencyError(ToolError):
    """Raised when a required dependency is missing"""

    def __init__(
        self,
        message: str,
        dependency_name: str,
        install_command: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        details["dependency_name"] = dependency_name
        if install_command:
            details["install_command"] = install_command

        super().__init__(
            message,
            error_code=ErrorCode.TOOL_DEPENDENCY_MISSING,
            details=details
        )


class ToolNotFoundError(ToolError):
    """Raised when a requested tool is not found in registry"""

    def __init__(
        self,
        tool_name: str,
        available_tools: Optional[list] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        message = f"Tool '{tool_name}' not found in registry"
        details = details or {}
        details["requested_tool"] = tool_name
        if available_tools:
            details["available_tools"] = available_tools

        super().__init__(
            message,
            error_code=ErrorCode.TOOL_NOT_FOUND,
            details=details
        )


# ============================================================================
# Network Errors
# ============================================================================

class NetworkError(AgentOSError):
    """Base class for network-related errors"""
    pass


class NetworkTimeoutError(NetworkError):
    """Raised when a network request times out"""

    def __init__(
        self,
        message: str,
        url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        if url:
            details["url"] = url
        if timeout_seconds:
            details["timeout_seconds"] = timeout_seconds

        super().__init__(
            message,
            error_code=ErrorCode.NETWORK_TIMEOUT,
            details=details
        )


class HTTPError(NetworkError):
    """Raised when an HTTP request fails"""

    def __init__(
        self,
        message: str,
        status_code: int,
        url: Optional[str] = None,
        response_text: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        details["status_code"] = status_code
        if url:
            details["url"] = url
        if response_text:
            details["response_preview"] = response_text[:200]  # Truncate

        # Map status code to specific error code
        error_code_map = {
            400: ErrorCode.HTTP_400,
            401: ErrorCode.HTTP_401,
            403: ErrorCode.HTTP_403,
            404: ErrorCode.HTTP_404,
            429: ErrorCode.HTTP_429,
            500: ErrorCode.HTTP_500,
            502: ErrorCode.HTTP_502,
            503: ErrorCode.HTTP_503,
        }
        error_code = error_code_map.get(status_code, ErrorCode.HTTP_ERROR)

        super().__init__(message, error_code, details)


# ============================================================================
# Database Errors
# ============================================================================

class DatabaseError(AgentOSError):
    """Base class for database-related errors"""
    pass


class DatabaseConnectionError(DatabaseError):
    """Raised when database connection fails"""

    def __init__(
        self,
        message: str,
        database_url: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None
    ):
        details = details or {}
        if database_url:
            # Mask credentials in URL
            details["database_url"] = self._mask_credentials(database_url)

        super().__init__(
            message,
            error_code=ErrorCode.DB_CONNECTION_ERROR,
            details=details,
            original_error=original_error
        )

    @staticmethod
    def _mask_credentials(url: str) -> str:
        """Mask credentials in database URL for logging"""
        import re
        return re.sub(r'://([^:]+):([^@]+)@', r'://\1:***@', url)


class DatabaseQueryError(DatabaseError):
    """Raised when a database query fails"""

    def __init__(
        self,
        message: str,
        query: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None
    ):
        details = details or {}
        if query:
            # Truncate long queries
            details["query_preview"] = query[:200] if len(query) > 200 else query

        super().__init__(
            message,
            error_code=ErrorCode.DB_QUERY_ERROR,
            details=details,
            original_error=original_error
        )


# ============================================================================
# Security Errors
# ============================================================================

class SecurityError(AgentOSError):
    """Base class for security-related errors"""
    pass


class SecurityValidationError(SecurityError):
    """Raised when security validation fails"""

    def __init__(
        self,
        message: str,
        validation_type: str,
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        details["validation_type"] = validation_type

        super().__init__(
            message,
            error_code=ErrorCode.SECURITY_VALIDATION_FAILED,
            details=details
        )


class SQLInjectionError(SecurityError):
    """Raised when potential SQL injection is detected"""

    def __init__(
        self,
        message: str = "Potential SQL injection detected",
        query_preview: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        if query_preview:
            details["query_preview"] = query_preview[:100]

        super().__init__(
            message,
            error_code=ErrorCode.SECURITY_SQL_INJECTION,
            details=details
        )


# ============================================================================
# Resource Errors
# ============================================================================

class ResourceError(AgentOSError):
    """Base class for resource-related errors"""
    pass


class ResourceNotFoundError(ResourceError):
    """Raised when a resource is not found"""

    def __init__(
        self,
        resource_type: str,
        resource_id: str,
        details: Optional[Dict[str, Any]] = None
    ):
        message = f"{resource_type} not found: {resource_id}"
        details = details or {}
        details["resource_type"] = resource_type
        details["resource_id"] = resource_id

        super().__init__(
            message,
            error_code=ErrorCode.RESOURCE_NOT_FOUND,
            details=details
        )


class FileError(ResourceError):
    """Base class for file-related errors"""
    pass


class FileNotFoundError(FileError):
    """Raised when a file is not found"""

    def __init__(
        self,
        file_path: str,
        details: Optional[Dict[str, Any]] = None
    ):
        message = f"File not found: {file_path}"
        details = details or {}
        details["file_path"] = file_path

        super().__init__(
            message,
            error_code=ErrorCode.FILE_NOT_FOUND,
            details=details
        )


class FilePermissionError(FileError):
    """Raised when file permissions are insufficient"""

    def __init__(
        self,
        file_path: str,
        operation: str,
        details: Optional[Dict[str, Any]] = None
    ):
        message = f"Permission denied: Cannot {operation} file {file_path}"
        details = details or {}
        details["file_path"] = file_path
        details["operation"] = operation

        super().__init__(
            message,
            error_code=ErrorCode.FILE_PERMISSION_ERROR,
            details=details
        )


# ============================================================================
# Configuration Errors
# ============================================================================

class ConfigError(AgentOSError):
    """Base class for configuration-related errors"""
    pass


class ConfigLoadError(ConfigError):
    """Raised when config file cannot be loaded"""

    def __init__(
        self,
        message: str,
        config_path: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None
    ):
        details = details or {}
        if config_path:
            details["config_path"] = config_path

        super().__init__(
            message,
            error_code=ErrorCode.CONFIG_INVALID,
            details=details,
            original_error=original_error
        )


class ConfigValidationError(ConfigError):
    """Raised when configuration validation fails"""

    def __init__(
        self,
        message: str,
        field_path: Optional[str] = None,
        expected_type: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        if field_path:
            details["field_path"] = field_path
        if expected_type:
            details["expected_type"] = expected_type

        super().__init__(
            message,
            error_code=ErrorCode.CONFIG_TYPE_ERROR,
            details=details
        )


# ============================================================================
# Agent Errors
# ============================================================================

class AgentError(AgentOSError):
    """Base class for agent-related errors"""
    pass


class AgentConfigError(AgentError):
    """Raised when agent configuration is invalid"""

    def __init__(
        self,
        message: str,
        agent_name: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        if agent_name:
            details["agent_name"] = agent_name

        super().__init__(
            message,
            error_code=ErrorCode.AGENT_INITIALIZATION_ERROR,
            details=details
        )


# ============================================================================
# Workflow Errors
# ============================================================================

class WorkflowError(AgentOSError):
    """Base class for workflow-related errors"""
    pass


class WorkflowExecutionError(WorkflowError):
    """Raised when workflow execution fails"""

    def __init__(
        self,
        message: str,
        workflow_name: Optional[str] = None,
        current_step: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None
    ):
        details = details or {}
        if workflow_name:
            details["workflow_name"] = workflow_name
        if current_step:
            details["current_step"] = current_step

        super().__init__(
            message,
            error_code=ErrorCode.WORKFLOW_EXECUTION_ERROR,
            details=details,
            original_error=original_error
        )
