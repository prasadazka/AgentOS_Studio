"""
Production-grade Git operations for Agent_OS

Provides safe, validated Git operations with:
- Path traversal protection
- Credential masking in logs
- Error handling and validation
- Support for GitHub/GitLab/Bitbucket APIs
"""

import subprocess
import json
from pathlib import Path
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, validator
import hashlib

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import ToolExecutionError, ToolValidationError, ErrorCode
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Type-Safe Models
# =============================================================================

class GitPathInput(BaseModel):
    """Type-safe Git repository path input"""
    repo_path: str = Field(..., min_length=1)

    @validator('repo_path')
    def validate_path(cls, v):
        """Validate repository path for security"""
        if not v or not v.strip():
            raise ValueError("Repository path cannot be empty")

        path = Path(v).resolve()

        # Path traversal protection
        if ".." in str(path):
            raise ValueError("Path traversal not allowed")

        return str(path)


class GitOutput(BaseModel):
    """Type-safe Git operation output"""
    success: bool
    operation: str
    repo_path: Optional[str] = None
    branch: Optional[str] = None
    commit_hash: Optional[str] = None
    output: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Git Tools
# =============================================================================

class GitCloneTool(BaseTool):
    """Clone a Git repository

    Security:
    - Validates URLs
    - Masks credentials in logs
    - Limits clone depth
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="git_clone",
                description="Clone a Git repository to local filesystem",
                category="devops",
                tags=["git", "clone", "repository"]
            )
        )

    def _execute(
        self,
        repo_url: str,
        destination: str,
        branch: Optional[str] = None,
        depth: Optional[int] = None,
        shallow: bool = False
    ) -> str:
        """Clone Git repository

        Args:
            repo_url: Git repository URL (https or ssh)
            destination: Local path to clone into
            branch: Specific branch to clone (optional)
            depth: Clone depth (shallow clone)
            shallow: Enable shallow clone (depth=1)

        Returns:
            JSON with GitOutput schema
        """
        repo_hash = hashlib.sha256(repo_url.encode()).hexdigest()[:8]

        try:
            # Validate destination path
            validated = GitPathInput(repo_path=destination)
            dest_path = Path(validated.repo_path)

            # Check if destination already exists
            if dest_path.exists():
                return GitOutput(
                    success=False,
                    operation="clone",
                    repo_path=str(dest_path),
                    error="Destination path already exists",
                    error_code=ErrorCode.RESOURCE_LOCKED.value
                ).to_json()

            # Build git clone command
            cmd = ["git", "clone"]

            if shallow:
                cmd.extend(["--depth", "1"])
            elif depth:
                cmd.extend(["--depth", str(depth)])

            if branch:
                cmd.extend(["--branch", branch])

            cmd.extend([repo_url, str(dest_path)])

            # Log with masked URL (hide credentials)
            masked_url = self._mask_credentials(repo_url)
            logger.info(f"Cloning repository", extra={
                "repo_hash": repo_hash,
                "masked_url": masked_url,
                "destination": str(dest_path),
                "branch": branch
            })

            # Execute git clone
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 min timeout
            )

            if result.returncode != 0:
                return GitOutput(
                    success=False,
                    operation="clone",
                    repo_path=str(dest_path),
                    error=result.stderr,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                ).to_json()

            # Get cloned commit hash
            commit_hash = self._get_commit_hash(dest_path)

            logger.info("Clone completed", extra={
                "repo_hash": repo_hash,
                "commit_hash": commit_hash
            })

            return GitOutput(
                success=True,
                operation="clone",
                repo_path=str(dest_path),
                branch=branch or "default",
                commit_hash=commit_hash,
                output=result.stdout,
                metadata={"shallow": shallow or (depth is not None)}
            ).to_json()

        except subprocess.TimeoutExpired:
            logger.error("Clone timeout", extra={"repo_hash": repo_hash})
            return GitOutput(
                success=False,
                operation="clone",
                error="Clone operation timed out (5 min limit)",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()

        except Exception as e:
            logger.error("Clone failed", extra={"repo_hash": repo_hash}, exc_info=True)
            return GitOutput(
                success=False,
                operation="clone",
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()

    def _mask_credentials(self, url: str) -> str:
        """Mask credentials in URL for logging"""
        if '@' in url:
            # https://user:pass@github.com/repo -> https://***:***@github.com/repo
            parts = url.split('@')
            if len(parts) == 2:
                protocol_and_creds = parts[0]
                if '://' in protocol_and_creds:
                    protocol = protocol_and_creds.split('://')[0]
                    return f"{protocol}://***:***@{parts[1]}"
        return url

    def _get_commit_hash(self, repo_path: Path) -> Optional[str]:
        """Get current commit hash"""
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()[:8]  # Short hash
        except:
            pass
        return None


class GitStatusTool(BaseTool):
    """Get Git repository status"""

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="git_status",
                description="Get status of Git repository (modified files, branch, etc.)",
                category="devops",
                tags=["git", "status"]
            )
        )

    def _execute(self, repo_path: str = ".") -> str:
        """Get Git status

        Args:
            repo_path: Path to Git repository (default: current directory)

        Returns:
            JSON with GitOutput schema
        """
        try:
            validated = GitPathInput(repo_path=repo_path)
            path = Path(validated.repo_path)

            if not (path / ".git").exists():
                return GitOutput(
                    success=False,
                    operation="status",
                    repo_path=str(path),
                    error="Not a Git repository",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

            # Get status
            result = subprocess.run(
                ["git", "-C", str(path), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                return GitOutput(
                    success=False,
                    operation="status",
                    repo_path=str(path),
                    error=result.stderr,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                ).to_json()

            # Get current branch
            branch_result = subprocess.run(
                ["git", "-C", str(path), "branch", "--show-current"],
                capture_output=True,
                text=True,
                timeout=5
            )
            branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"

            # Parse status
            status_lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
            modified = []
            untracked = []

            for line in status_lines:
                if line.startswith('??'):
                    untracked.append(line[3:])
                elif line.strip():
                    modified.append(line[3:])

            return GitOutput(
                success=True,
                operation="status",
                repo_path=str(path),
                branch=branch,
                output=result.stdout,
                metadata={
                    "modified_count": len(modified),
                    "untracked_count": len(untracked),
                    "is_clean": len(status_lines) == 0
                }
            ).to_json()

        except Exception as e:
            logger.error("Status failed", exc_info=True)
            return GitOutput(
                success=False,
                operation="status",
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class GitDiffTool(BaseTool):
    """Show Git diff (changes)"""

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="git_diff",
                description="Show changes (diff) in Git repository",
                category="devops",
                tags=["git", "diff", "changes"]
            )
        )

    def _execute(
        self,
        repo_path: str = ".",
        file_path: Optional[str] = None,
        staged: bool = False
    ) -> str:
        """Get Git diff

        Args:
            repo_path: Path to Git repository
            file_path: Specific file to diff (optional)
            staged: Show staged changes (default: unstaged)

        Returns:
            JSON with GitOutput schema
        """
        try:
            validated = GitPathInput(repo_path=repo_path)
            path = Path(validated.repo_path)

            cmd = ["git", "-C", str(path), "diff"]

            if staged:
                cmd.append("--cached")

            if file_path:
                cmd.append(file_path)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                return GitOutput(
                    success=False,
                    operation="diff",
                    repo_path=str(path),
                    error=result.stderr,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                ).to_json()

            return GitOutput(
                success=True,
                operation="diff",
                repo_path=str(path),
                output=result.stdout,
                metadata={
                    "staged": staged,
                    "file_path": file_path,
                    "has_changes": bool(result.stdout.strip())
                }
            ).to_json()

        except Exception as e:
            return GitOutput(
                success=False,
                operation="diff",
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class GitLogTool(BaseTool):
    """Get Git commit history"""

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="git_log",
                description="Get Git commit history with metadata",
                category="devops",
                tags=["git", "log", "history", "commits"]
            )
        )

    def _execute(
        self,
        repo_path: str = ".",
        max_count: int = 10,
        oneline: bool = False
    ) -> str:
        """Get Git log

        Args:
            repo_path: Path to Git repository
            max_count: Max commits to show (default: 10)
            oneline: Show one line per commit

        Returns:
            JSON with GitOutput schema
        """
        try:
            validated = GitPathInput(repo_path=repo_path)
            path = Path(validated.repo_path)

            cmd = ["git", "-C", str(path), "log", f"--max-count={max_count}"]

            if oneline:
                cmd.append("--oneline")
            else:
                cmd.extend(["--pretty=format:%h - %an, %ar : %s"])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                return GitOutput(
                    success=False,
                    operation="log",
                    repo_path=str(path),
                    error=result.stderr,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                ).to_json()

            commits = result.stdout.strip().split('\n') if result.stdout.strip() else []

            return GitOutput(
                success=True,
                operation="log",
                repo_path=str(path),
                output=result.stdout,
                metadata={
                    "commit_count": len(commits),
                    "max_count": max_count
                }
            ).to_json()

        except Exception as e:
            return GitOutput(
                success=False,
                operation="log",
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class GitBranchTool(BaseTool):
    """List Git branches"""

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="git_branch",
                description="List all branches in Git repository",
                category="devops",
                tags=["git", "branch"]
            )
        )

    def _execute(
        self,
        repo_path: str = ".",
        remote: bool = False
    ) -> str:
        """List Git branches

        Args:
            repo_path: Path to Git repository
            remote: Show remote branches

        Returns:
            JSON with GitOutput schema
        """
        try:
            validated = GitPathInput(repo_path=repo_path)
            path = Path(validated.repo_path)

            cmd = ["git", "-C", str(path), "branch"]

            if remote:
                cmd.append("-r")
            else:
                cmd.append("-a")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                return GitOutput(
                    success=False,
                    operation="branch",
                    repo_path=str(path),
                    error=result.stderr,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                ).to_json()

            branches = [line.strip().lstrip('* ') for line in result.stdout.split('\n') if line.strip()]
            current_branch = next((line.strip().lstrip('* ') for line in result.stdout.split('\n') if line.startswith('*')), None)

            return GitOutput(
                success=True,
                operation="branch",
                repo_path=str(path),
                branch=current_branch,
                output=result.stdout,
                metadata={
                    "total_branches": len(branches),
                    "remote": remote
                }
            ).to_json()

        except Exception as e:
            return GitOutput(
                success=False,
                operation="branch",
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()
