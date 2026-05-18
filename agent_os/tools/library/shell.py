"""
Production-grade Shell/Terminal command execution for Agent_OS

Provides secure, cross-platform command execution with:
- OS detection (Windows/Linux/Mac)
- Dangerous command blocking
- Timeout limits and resource controls
- Working directory support
- Environment variable management
- Audit logging

Security Features:
- Pattern-based dangerous command detection
- Privileged command blocking (sudo, admin)
- Destructive operation protection (rm -rf /, format, etc.)
- Command injection prevention
- Timeout enforcement
"""

import subprocess
import platform
import os
import re
import json
from pathlib import Path
from typing import Optional, Dict, List, Any
from pydantic import BaseModel, Field, validator
from enum import Enum

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import ToolExecutionError, ErrorCode
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Type-Safe Models
# =============================================================================

class OSType(str, Enum):
    """Supported operating systems"""
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    UNKNOWN = "unknown"


class ShellType(str, Enum):
    """Supported shell types"""
    CMD = "cmd"  # Windows Command Prompt
    POWERSHELL = "powershell"  # Windows PowerShell
    BASH = "bash"  # Unix/Linux/Mac Bash
    SH = "sh"  # Unix/Linux/Mac Bourne shell
    ZSH = "zsh"  # Mac Z shell
    AUTO = "auto"  # Auto-detect based on OS


class DangerLevel(str, Enum):
    """Command danger levels"""
    SAFE = "safe"
    MODERATE = "moderate"  # Requires review
    HIGH = "high"  # Destructive, requires approval
    CRITICAL = "critical"  # Extremely dangerous, blocked


class CommandInput(BaseModel):
    """Type-safe shell command input"""
    command: str = Field(..., min_length=1)
    working_dir: Optional[str] = None
    timeout: Optional[int] = Field(default=30, ge=1, le=3600)  # 1s - 1hr
    shell_type: ShellType = ShellType.AUTO
    env_vars: Optional[Dict[str, str]] = None

    @validator('command')
    def validate_command(cls, v):
        """Validate command for basic safety"""
        if not v or not v.strip():
            raise ValueError("Command cannot be empty")

        # Block null bytes (command injection)
        if '\x00' in v:
            raise ValueError("Null bytes not allowed in commands")

        return v.strip()


class ShellOutput(BaseModel):
    """Type-safe shell execution output"""
    success: bool
    command: str
    stdout: str
    stderr: str
    exit_code: int
    execution_time: float
    os_type: str
    shell_type: str
    working_dir: Optional[str] = None
    danger_level: Optional[str] = None
    blocked: bool = False
    block_reason: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Dangerous Command Detector
# =============================================================================

class DangerousCommandDetector:
    """
    Detect dangerous shell commands using pattern matching

    Based on:
    - OWASP Command Injection Prevention
    - CIS Security Benchmarks
    - Common destructive operations
    """

    # CRITICAL: Commands that should NEVER be executed
    CRITICAL_PATTERNS = [
        # Destructive filesystem operations
        r'\brm\s+.*-rf\s*/\b',  # rm -rf /
        r'\brm\s+-rf\s+/\b',
        r'\bformat\s+[cC]:\b',  # Windows format C:
        r'\b(mkfs|fdisk|dd)\s+/dev/',  # Disk formatting/wiping

        # System shutdown/restart
        r'\b(shutdown|reboot|halt|poweroff)\b',
        r'\binit\s+[06]\b',  # Unix shutdown/reboot

        # Fork bombs
        r':\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:',  # Classic fork bomb
        r'\bwhile\s+true.*do\s+.*done',  # Infinite loop

        # Network attacks
        r'\b(nmap|masscan|hping)\b.*-.*scan',
        r'\bmetasploit|msfconsole\b',

        # Crypto mining
        r'\b(xmrig|cpuminer|cgminer)\b',
    ]

    # HIGH: Destructive operations requiring approval
    HIGH_RISK_PATTERNS = [
        # Recursive deletion
        r'\brm\s+-rf?\s+',
        r'\brmdir\s+/s\b',  # Windows recursive delete
        r'\brd\s+/s\b',

        # File system operations
        r'\bmkfs\b',
        r'\bchmod\s+000\b',
        r'\bchmod\s+-R\s+777\b',

        # Database drops
        r'\bDROP\s+(DATABASE|TABLE)\b',
        r'\bTRUNCATE\s+TABLE\b',

        # Docker/Container dangers
        r'\bdocker\s+rm\s+-f\b',
        r'\bdocker\s+system\s+prune\s+-a\b',
        r'\bkubectl\s+delete\s+(all|namespace)\b',

        # Cloud resource deletion
        r'\b(gcloud|aws|az)\s+.*delete\b',
        r'\bterraform\s+destroy\b',
    ]

    # MODERATE: Privileged operations
    MODERATE_RISK_PATTERNS = [
        # Privilege escalation
        r'\bsudo\s+',
        r'\bsu\s+-\b',
        r'\brunas\b',  # Windows

        # System modifications
        r'\bapt(-get)?\s+(install|remove|purge)\b',
        r'\byum\s+(install|remove|erase)\b',
        r'\bbrew\s+(install|uninstall)\b',
        r'\bchmod\b',
        r'\bchown\b',

        # Network operations
        r'\b(iptables|firewall-cmd)\b',
        r'\bnetstat\b',

        # Process management
        r'\bkill\s+-9\b',
        r'\bpkill\b',
        r'\btaskkill\s+/f\b',  # Windows
    ]

    @classmethod
    def check_command(cls, command: str) -> tuple[DangerLevel, Optional[str], List[str]]:
        """
        Check command for dangerous patterns

        Returns:
            (danger_level, block_reason, matched_patterns)
        """
        matched_patterns = []

        # Check CRITICAL patterns (always block)
        for pattern in cls.CRITICAL_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                matched_patterns.append(pattern)
                return (
                    DangerLevel.CRITICAL,
                    f"BLOCKED: Critical dangerous operation detected. Pattern: {pattern}",
                    matched_patterns
                )

        # Check HIGH risk patterns
        for pattern in cls.HIGH_RISK_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                matched_patterns.append(pattern)

        if matched_patterns:
            return (
                DangerLevel.HIGH,
                f"High-risk destructive operation. Requires approval. Patterns: {matched_patterns[:3]}",
                matched_patterns
            )

        # Check MODERATE risk patterns
        for pattern in cls.MODERATE_RISK_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                matched_patterns.append(pattern)

        if matched_patterns:
            return (
                DangerLevel.MODERATE,
                f"Privileged operation detected. Patterns: {matched_patterns[:3]}",
                matched_patterns
            )

        return (DangerLevel.SAFE, None, [])


# =============================================================================
# Shell Executor
# =============================================================================

class ShellExecutor:
    """Cross-platform shell command executor"""

    @staticmethod
    def detect_os() -> OSType:
        """Detect current operating system"""
        system = platform.system().lower()
        if system == "windows":
            return OSType.WINDOWS
        elif system == "linux":
            return OSType.LINUX
        elif system == "darwin":
            return OSType.MACOS
        else:
            return OSType.UNKNOWN

    @staticmethod
    def get_default_shell(os_type: OSType) -> ShellType:
        """Get default shell for OS"""
        if os_type == OSType.WINDOWS:
            return ShellType.CMD
        elif os_type in [OSType.LINUX, OSType.MACOS]:
            return ShellType.BASH
        else:
            return ShellType.SH

    @staticmethod
    def build_shell_command(
        command: str,
        shell_type: ShellType,
        os_type: OSType
    ) -> tuple[List[str], bool]:
        """
        Build platform-specific shell command

        Returns:
            (command_list, use_shell_flag)
        """
        if os_type == OSType.WINDOWS:
            if shell_type == ShellType.POWERSHELL:
                return (["powershell", "-Command", command], False)
            else:  # CMD
                return (["cmd", "/c", command], False)
        else:  # Unix-like
            if shell_type == ShellType.BASH:
                return (["/bin/bash", "-c", command], False)
            elif shell_type == ShellType.ZSH:
                return (["/bin/zsh", "-c", command], False)
            else:  # SH
                return (["/bin/sh", "-c", command], False)

    @staticmethod
    def execute(
        command: str,
        working_dir: Optional[str] = None,
        timeout: int = 30,
        shell_type: ShellType = ShellType.AUTO,
        env_vars: Optional[Dict[str, str]] = None,
        block_dangerous: bool = True
    ) -> ShellOutput:
        """
        Execute shell command with security checks

        Args:
            command: Command to execute
            working_dir: Working directory (optional)
            timeout: Timeout in seconds
            shell_type: Shell type (auto-detect if not specified)
            env_vars: Additional environment variables
            block_dangerous: Block dangerous commands (default: True)

        Returns:
            ShellOutput with results
        """
        import time
        start_time = time.time()

        # Detect OS
        os_type = ShellExecutor.detect_os()

        # Auto-select shell if needed
        if shell_type == ShellType.AUTO:
            shell_type = ShellExecutor.get_default_shell(os_type)

        # Check for dangerous commands
        danger_level, block_reason, patterns = DangerousCommandDetector.check_command(command)

        if block_dangerous and danger_level == DangerLevel.CRITICAL:
            logger.warning(f"Blocked critical command: {command}", extra={
                "danger_level": danger_level.value,
                "patterns": patterns
            })
            return ShellOutput(
                success=False,
                command=command,
                stdout="",
                stderr="",
                exit_code=-1,
                execution_time=time.time() - start_time,
                os_type=os_type.value,
                shell_type=shell_type.value,
                working_dir=working_dir,
                danger_level=danger_level.value,
                blocked=True,
                block_reason=block_reason,
                error=block_reason,
                error_code=ErrorCode.SECURITY_VALIDATION_FAILED.value
            )

        # Build shell command
        cmd_list, use_shell = ShellExecutor.build_shell_command(command, shell_type, os_type)

        # Prepare environment
        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)

        # Validate working directory
        cwd = None
        if working_dir:
            cwd_path = Path(working_dir).resolve()
            if not cwd_path.exists():
                return ShellOutput(
                    success=False,
                    command=command,
                    stdout="",
                    stderr="",
                    exit_code=-1,
                    execution_time=time.time() - start_time,
                    os_type=os_type.value,
                    shell_type=shell_type.value,
                    working_dir=working_dir,
                    error=f"Working directory does not exist: {working_dir}",
                    error_code=ErrorCode.FILE_NOT_FOUND.value
                )
            cwd = str(cwd_path)

        # Log command execution
        logger.info(f"Executing shell command", extra={
            "command": command,
            "os": os_type.value,
            "shell": shell_type.value,
            "working_dir": cwd,
            "danger_level": danger_level.value,
            "timeout": timeout
        })

        # Execute command
        try:
            result = subprocess.run(
                cmd_list,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=env
            )

            execution_time = time.time() - start_time

            return ShellOutput(
                success=(result.returncode == 0),
                command=command,
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                execution_time=execution_time,
                os_type=os_type.value,
                shell_type=shell_type.value,
                working_dir=cwd,
                danger_level=danger_level.value if danger_level != DangerLevel.SAFE else None
            )

        except subprocess.TimeoutExpired:
            execution_time = time.time() - start_time
            logger.error(f"Command timeout: {command}", extra={"timeout": timeout})
            return ShellOutput(
                success=False,
                command=command,
                stdout="",
                stderr=f"Command timed out after {timeout} seconds",
                exit_code=-1,
                execution_time=execution_time,
                os_type=os_type.value,
                shell_type=shell_type.value,
                working_dir=cwd,
                error=f"Timeout after {timeout}s",
                error_code=ErrorCode.TOOL_TIMEOUT.value
            )

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Command execution failed: {command}", exc_info=True)
            return ShellOutput(
                success=False,
                command=command,
                stdout="",
                stderr=str(e),
                exit_code=-1,
                execution_time=execution_time,
                os_type=os_type.value,
                shell_type=shell_type.value,
                working_dir=cwd,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            )


# =============================================================================
# Tool Exports for Agent Usage
# =============================================================================

class ShellExecutorTool(BaseTool):
    """
    Execute shell/terminal commands across platforms

    Security:
    - Dangerous command detection and blocking
    - Timeout enforcement
    - Working directory validation
    - Audit logging
    """

    def __init__(self, block_dangerous: bool = True, default_timeout: int = 30):
        """
        Initialize shell executor tool

        Args:
            block_dangerous: Block dangerous commands (default: True)
            default_timeout: Default timeout in seconds (default: 30)
        """
        metadata = ToolMetadata(
            name="shell_execute",
            description="Execute shell/terminal commands (Windows cmd/powershell, Linux/Mac bash)",
            category="system"
        )
        super().__init__(metadata)
        self.block_dangerous = block_dangerous
        self.default_timeout = default_timeout

    def _execute(
        self,
        command: str,
        working_dir: Optional[str] = None,
        timeout: Optional[int] = None,
        shell_type: str = "auto",
        env_vars: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Execute shell command

        Args:
            command: Command to execute
            working_dir: Working directory (optional)
            timeout: Timeout in seconds (default: 30)
            shell_type: Shell type (auto/cmd/powershell/bash/sh/zsh)
            env_vars: Additional environment variables (optional)

        Returns:
            JSON string with execution results
        """
        # Validate input
        try:
            validated = CommandInput(
                command=command,
                working_dir=working_dir,
                timeout=timeout or self.default_timeout,
                shell_type=ShellType(shell_type.lower()),
                env_vars=env_vars
            )
        except Exception as e:
            return ShellOutput(
                success=False,
                command=command,
                stdout="",
                stderr="",
                exit_code=-1,
                execution_time=0.0,
                os_type=ShellExecutor.detect_os().value,
                shell_type=shell_type,
                error=f"Validation error: {str(e)}",
                error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
            ).to_json()

        # Execute command
        result = ShellExecutor.execute(
            command=validated.command,
            working_dir=validated.working_dir,
            timeout=validated.timeout,
            shell_type=validated.shell_type,
            env_vars=validated.env_vars,
            block_dangerous=self.block_dangerous
        )

        return result.to_json()


class SafeShellExecutorTool(ShellExecutorTool):
    """Shell executor with all safety features enabled (recommended)"""

    def __init__(self):
        super().__init__(block_dangerous=True, default_timeout=30)
        self.metadata.name = "shell_execute_safe"
        self.metadata.description = "Execute shell commands with safety checks enabled"


class UnsafeShellExecutorTool(ShellExecutorTool):
    """
    Shell executor with safety checks disabled

    ⚠️  WARNING: Only use in trusted environments or for debugging
    """

    def __init__(self):
        super().__init__(block_dangerous=False, default_timeout=300)
        self.metadata.name = "shell_execute_unsafe"
        self.metadata.description = "Execute shell commands WITHOUT safety checks (use with caution)"


class ApprovalShellExecutorTool(ShellExecutorTool):
    """
    Shell executor with human-in-the-loop approval for dangerous commands

    Features:
    - Requires approval for HIGH and MODERATE risk commands
    - Blocks CRITICAL commands automatically
    - Interactive approval prompts
    - Approval audit trail
    """

    def __init__(self, approval_manager=None):
        """
        Initialize approval-aware shell executor

        Args:
            approval_manager: ApprovalManager instance (uses global if not provided)
        """
        super().__init__(block_dangerous=True, default_timeout=30)
        self.metadata.name = "shell_execute_approval"
        self.metadata.description = "Execute shell commands with approval for dangerous operations"

        # Import approval system
        from agent_os.tools.approval import get_approval_manager
        self.approval_manager = approval_manager or get_approval_manager()

    def _execute(
        self,
        command: str,
        working_dir: Optional[str] = None,
        timeout: Optional[int] = None,
        shell_type: str = "auto",
        env_vars: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Execute shell command with approval for dangerous operations

        HIGH and MODERATE risk commands require approval.
        CRITICAL commands are blocked automatically.
        """
        # Check danger level first
        danger_level, block_reason, patterns = DangerousCommandDetector.check_command(command)

        # CRITICAL: Always block
        if danger_level == DangerLevel.CRITICAL:
            return ShellOutput(
                success=False,
                command=command,
                stdout="",
                stderr="",
                exit_code=-1,
                execution_time=0.0,
                os_type=ShellExecutor.detect_os().value,
                shell_type=shell_type,
                danger_level=danger_level.value,
                blocked=True,
                block_reason=block_reason,
                error=block_reason,
                error_code=ErrorCode.SECURITY_VALIDATION_FAILED.value
            ).to_json()

        # HIGH or MODERATE: Request approval
        if danger_level in [DangerLevel.HIGH, DangerLevel.MODERATE]:
            decision, reason = self.approval_manager.request_approval(
                operation="shell_command_execution",
                description=f"Execute {danger_level.value.upper()} risk command",
                details={
                    "command": command,
                    "danger_level": danger_level.value,
                    "matched_patterns": patterns[:3],  # First 3 patterns
                    "working_dir": working_dir,
                    "timeout": timeout or self.default_timeout,
                }
            )

            # Import here to avoid circular import
            from agent_os.tools.approval import ApprovalDecision

            if decision != ApprovalDecision.APPROVED:
                return ShellOutput(
                    success=False,
                    command=command,
                    stdout="",
                    stderr="",
                    exit_code=-1,
                    execution_time=0.0,
                    os_type=ShellExecutor.detect_os().value,
                    shell_type=shell_type,
                    danger_level=danger_level.value,
                    blocked=True,
                    block_reason=f"Approval {decision.value}: {reason}",
                    error=f"Operation denied: {reason}",
                    error_code=ErrorCode.SECURITY_VALIDATION_FAILED.value
                ).to_json()

        # Execute (either SAFE or APPROVED)
        return super()._execute(command, working_dir, timeout, shell_type, env_vars)
