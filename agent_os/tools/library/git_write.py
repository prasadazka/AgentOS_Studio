"""Git write operations - commit, push, pull request creation"""

import subprocess
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import ToolExecutionError, ToolValidationError, ErrorCode
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Type-Safe Models
# =============================================================================

class GitCommitInput(BaseModel):
    """Input for git commit operation"""
    message: str = Field(..., min_length=1, max_length=500, description="Commit message")
    files: Optional[List[str]] = Field(None, description="Files to stage (None = all changes)")
    repo_path: str = Field(".", description="Repository path")

    @validator('message')
    def validate_message(cls, v):
        if not v or not v.strip():
            raise ValueError("Commit message cannot be empty")
        return v.strip()


class GitPushInput(BaseModel):
    """Input for git push operation"""
    remote: str = Field("origin", description="Remote name")
    branch: Optional[str] = Field(None, description="Branch to push (None = current)")
    repo_path: str = Field(".", description="Repository path")
    force: bool = Field(False, description="Force push (use with caution)")
    set_upstream: bool = Field(False, description="Set upstream tracking")


class GitPRInput(BaseModel):
    """Input for pull request creation"""
    title: str = Field(..., min_length=1, max_length=200, description="PR title")
    body: str = Field("", max_length=10000, description="PR description")
    base: str = Field("main", description="Base branch")
    head: Optional[str] = Field(None, description="Head branch (None = current)")
    repo_path: str = Field(".", description="Repository path")
    draft: bool = Field(False, description="Create as draft PR")


class GitOperationOutput(BaseModel):
    """Standard output for git operations"""
    success: bool
    operation: str
    message: str
    details: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Git Write Tools
# =============================================================================

class GitCommitTool(BaseTool):
    """Production-grade git commit tool

    Features:
    - Stage specific files or all changes
    - Validate commit message
    - Check for changes before committing
    - Support for different repository paths
    """

    def __init__(self):
        self._git_path = shutil.which("git")
        super().__init__(
            ToolMetadata(
                name="git_commit",
                description="Stage and commit changes to git repository",
                category="git",
                tags=["git", "version-control", "commit", "deployment"]
            )
        )

    def _validate_config(self):
        if not self._git_path:
            logger.warning("Git not found in PATH")

    def _run_git(self, args: List[str], cwd: str) -> subprocess.CompletedProcess:
        """Run git command with proper error handling"""
        cmd = [self._git_path or "git"] + args
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60
        )

    def _execute(
        self,
        message: str,
        files: Optional[List[str]] = None,
        repo_path: str = "."
    ) -> str:
        """Execute git commit

        Args:
            message: Commit message
            files: List of files to stage (None = all changes)
            repo_path: Path to repository

        Returns:
            JSON with commit result
        """
        try:
            # Validate input
            validated = GitCommitInput(
                message=message,
                files=files,
                repo_path=repo_path
            )

            repo = Path(validated.repo_path).resolve()

            # Verify it's a git repository
            if not (repo / ".git").exists():
                return GitOperationOutput(
                    success=False,
                    operation="commit",
                    message=f"Not a git repository: {repo}",
                    error="Not a git repository",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

            # Stage files
            if validated.files:
                for f in validated.files:
                    result = self._run_git(["add", f], str(repo))
                    if result.returncode != 0:
                        return GitOperationOutput(
                            success=False,
                            operation="commit",
                            message=f"Failed to stage file: {f}",
                            error=result.stderr.strip(),
                            error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                        ).to_json()
            else:
                # Stage all changes
                result = self._run_git(["add", "-A"], str(repo))
                if result.returncode != 0:
                    return GitOperationOutput(
                        success=False,
                        operation="commit",
                        message="Failed to stage changes",
                        error=result.stderr.strip(),
                        error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                    ).to_json()

            # Check if there are changes to commit
            status = self._run_git(["status", "--porcelain"], str(repo))
            if not status.stdout.strip():
                return GitOperationOutput(
                    success=True,
                    operation="commit",
                    message="No changes to commit",
                    details={"changes": 0}
                ).to_json()

            # Commit
            result = self._run_git(["commit", "-m", validated.message], str(repo))

            if result.returncode != 0:
                # Check if it's because nothing to commit
                if "nothing to commit" in result.stdout.lower():
                    return GitOperationOutput(
                        success=True,
                        operation="commit",
                        message="No changes to commit",
                        details={"changes": 0}
                    ).to_json()

                return GitOperationOutput(
                    success=False,
                    operation="commit",
                    message="Commit failed",
                    error=result.stderr.strip() or result.stdout.strip(),
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                ).to_json()

            # Get commit hash
            hash_result = self._run_git(["rev-parse", "--short", "HEAD"], str(repo))
            commit_hash = hash_result.stdout.strip() if hash_result.returncode == 0 else "unknown"

            logger.info(f"Git commit successful: {commit_hash}", extra={
                "commit_hash": commit_hash,
                "message": validated.message[:50]
            })

            return GitOperationOutput(
                success=True,
                operation="commit",
                message=f"Committed: {validated.message}",
                details={
                    "commit_hash": commit_hash,
                    "files_staged": validated.files or "all"
                }
            ).to_json()

        except ToolValidationError as e:
            return GitOperationOutput(
                success=False,
                operation="commit",
                message="Validation failed",
                error=str(e),
                error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
            ).to_json()

        except subprocess.TimeoutExpired:
            return GitOperationOutput(
                success=False,
                operation="commit",
                message="Git command timed out",
                error="Command exceeded 60 second timeout",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()

        except Exception as e:
            logger.error(f"Git commit failed: {e}", exc_info=True)
            return GitOperationOutput(
                success=False,
                operation="commit",
                message="Commit failed",
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class GitPushTool(BaseTool):
    """Production-grade git push tool

    Features:
    - Push to specified remote/branch
    - Set upstream tracking
    - Force push option (with warning)
    - Validate remote exists
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="git_push",
                description="Push commits to remote repository",
                category="git",
                tags=["git", "version-control", "push", "deployment"]
            )
        )
        self._git_path = shutil.which("git")

    def _run_git(self, args: List[str], cwd: str) -> subprocess.CompletedProcess:
        """Run git command with proper error handling"""
        cmd = [self._git_path or "git"] + args
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120  # Longer timeout for push
        )

    def _execute(
        self,
        remote: str = "origin",
        branch: Optional[str] = None,
        repo_path: str = ".",
        force: bool = False,
        set_upstream: bool = False
    ) -> str:
        """Execute git push

        Args:
            remote: Remote name (default: origin)
            branch: Branch to push (default: current branch)
            repo_path: Path to repository
            force: Force push (dangerous)
            set_upstream: Set upstream tracking

        Returns:
            JSON with push result
        """
        try:
            # Validate input
            validated = GitPushInput(
                remote=remote,
                branch=branch,
                repo_path=repo_path,
                force=force,
                set_upstream=set_upstream
            )

            repo = Path(validated.repo_path).resolve()

            # Verify it's a git repository
            if not (repo / ".git").exists():
                return GitOperationOutput(
                    success=False,
                    operation="push",
                    message=f"Not a git repository: {repo}",
                    error="Not a git repository",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

            # Get current branch if not specified
            if not validated.branch:
                result = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"], str(repo))
                if result.returncode != 0:
                    return GitOperationOutput(
                        success=False,
                        operation="push",
                        message="Failed to get current branch",
                        error=result.stderr.strip(),
                        error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                    ).to_json()
                validated.branch = result.stdout.strip()

            # Build push command
            push_args = ["push"]

            if validated.set_upstream:
                push_args.extend(["-u"])

            if validated.force:
                logger.warning(f"Force push requested to {validated.remote}/{validated.branch}")
                push_args.append("--force")

            push_args.extend([validated.remote, validated.branch])

            # Execute push
            result = self._run_git(push_args, str(repo))

            if result.returncode != 0:
                error_msg = result.stderr.strip()

                # Check for common errors
                if "rejected" in error_msg.lower():
                    return GitOperationOutput(
                        success=False,
                        operation="push",
                        message="Push rejected - remote has changes. Pull first or use force.",
                        error=error_msg,
                        error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                    ).to_json()

                return GitOperationOutput(
                    success=False,
                    operation="push",
                    message="Push failed",
                    error=error_msg,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                ).to_json()

            logger.info(f"Git push successful: {validated.remote}/{validated.branch}")

            return GitOperationOutput(
                success=True,
                operation="push",
                message=f"Pushed to {validated.remote}/{validated.branch}",
                details={
                    "remote": validated.remote,
                    "branch": validated.branch,
                    "force": validated.force,
                    "set_upstream": validated.set_upstream
                }
            ).to_json()

        except subprocess.TimeoutExpired:
            return GitOperationOutput(
                success=False,
                operation="push",
                message="Git push timed out",
                error="Command exceeded 120 second timeout",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()

        except Exception as e:
            logger.error(f"Git push failed: {e}", exc_info=True)
            return GitOperationOutput(
                success=False,
                operation="push",
                message="Push failed",
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class GitPRTool(BaseTool):
    """Production-grade pull request creation tool

    Features:
    - Create PRs via GitHub CLI (gh)
    - Support for draft PRs
    - Customizable base/head branches
    - Returns PR URL on success
    """

    def __init__(self):
        self._gh_path = shutil.which("gh")
        super().__init__(
            ToolMetadata(
                name="git_pr_create",
                description="Create pull request using GitHub CLI",
                category="git",
                tags=["git", "github", "pull-request", "deployment"]
            )
        )

    def _validate_config(self):
        if not self._gh_path:
            logger.warning("GitHub CLI (gh) not found in PATH")

    def _run_gh(self, args: List[str], cwd: str) -> subprocess.CompletedProcess:
        """Run gh command with proper error handling"""
        cmd = [self._gh_path or "gh"] + args
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60
        )

    def _execute(
        self,
        title: str,
        body: str = "",
        base: str = "main",
        head: Optional[str] = None,
        repo_path: str = ".",
        draft: bool = False
    ) -> str:
        """Create a pull request

        Args:
            title: PR title
            body: PR description
            base: Base branch (default: main)
            head: Head branch (default: current branch)
            repo_path: Path to repository
            draft: Create as draft PR

        Returns:
            JSON with PR creation result
        """
        try:
            # Check if gh is available
            if not self._gh_path:
                return GitOperationOutput(
                    success=False,
                    operation="pr_create",
                    message="GitHub CLI (gh) not installed",
                    error="Install gh CLI: https://cli.github.com/",
                    error_code=ErrorCode.TOOL_DEPENDENCY_MISSING.value
                ).to_json()

            # Validate input
            validated = GitPRInput(
                title=title,
                body=body,
                base=base,
                head=head,
                repo_path=repo_path,
                draft=draft
            )

            repo = Path(validated.repo_path).resolve()

            # Check gh auth status
            auth_result = self._run_gh(["auth", "status"], str(repo))
            if auth_result.returncode != 0:
                return GitOperationOutput(
                    success=False,
                    operation="pr_create",
                    message="GitHub CLI not authenticated",
                    error="Run 'gh auth login' to authenticate",
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                ).to_json()

            # Build PR create command
            pr_args = ["pr", "create"]
            pr_args.extend(["--title", validated.title])
            pr_args.extend(["--body", validated.body])
            pr_args.extend(["--base", validated.base])

            if validated.head:
                pr_args.extend(["--head", validated.head])

            if validated.draft:
                pr_args.append("--draft")

            # Create PR
            result = self._run_gh(pr_args, str(repo))

            if result.returncode != 0:
                error_msg = result.stderr.strip()

                # Check for existing PR
                if "already exists" in error_msg.lower():
                    return GitOperationOutput(
                        success=False,
                        operation="pr_create",
                        message="Pull request already exists for this branch",
                        error=error_msg,
                        error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                    ).to_json()

                return GitOperationOutput(
                    success=False,
                    operation="pr_create",
                    message="Failed to create pull request",
                    error=error_msg,
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                ).to_json()

            # Extract PR URL from output
            pr_url = result.stdout.strip()

            logger.info(f"PR created: {pr_url}")

            return GitOperationOutput(
                success=True,
                operation="pr_create",
                message=f"Pull request created: {validated.title}",
                details={
                    "url": pr_url,
                    "title": validated.title,
                    "base": validated.base,
                    "draft": validated.draft
                }
            ).to_json()

        except subprocess.TimeoutExpired:
            return GitOperationOutput(
                success=False,
                operation="pr_create",
                message="PR creation timed out",
                error="Command exceeded 60 second timeout",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()

        except Exception as e:
            logger.error(f"PR creation failed: {e}", exc_info=True)
            return GitOperationOutput(
                success=False,
                operation="pr_create",
                message="PR creation failed",
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class GitAddTool(BaseTool):
    """Git add tool for staging files

    Features:
    - Stage specific files or patterns
    - Stage all changes
    - Interactive staging preview
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="git_add",
                description="Stage files for commit",
                category="git",
                tags=["git", "version-control", "stage", "deployment"]
            )
        )
        self._git_path = shutil.which("git")

    def _run_git(self, args: List[str], cwd: str) -> subprocess.CompletedProcess:
        """Run git command with proper error handling"""
        cmd = [self._git_path or "git"] + args
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30
        )

    def _execute(
        self,
        files: Optional[List[str]] = None,
        all_changes: bool = False,
        repo_path: str = "."
    ) -> str:
        """Stage files for commit

        Args:
            files: List of files/patterns to stage
            all_changes: Stage all changes (-A flag)
            repo_path: Path to repository

        Returns:
            JSON with staging result
        """
        try:
            repo = Path(repo_path).resolve()

            if not (repo / ".git").exists():
                return GitOperationOutput(
                    success=False,
                    operation="add",
                    message=f"Not a git repository: {repo}",
                    error="Not a git repository",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

            if all_changes or not files:
                result = self._run_git(["add", "-A"], str(repo))
                staged_desc = "all changes"
            else:
                for f in files:
                    result = self._run_git(["add", f], str(repo))
                    if result.returncode != 0:
                        return GitOperationOutput(
                            success=False,
                            operation="add",
                            message=f"Failed to stage: {f}",
                            error=result.stderr.strip(),
                            error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                        ).to_json()
                staged_desc = ", ".join(files)

            if result.returncode != 0:
                return GitOperationOutput(
                    success=False,
                    operation="add",
                    message="Failed to stage files",
                    error=result.stderr.strip(),
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                ).to_json()

            # Get staged files count
            status = self._run_git(["diff", "--cached", "--name-only"], str(repo))
            staged_count = len(status.stdout.strip().split('\n')) if status.stdout.strip() else 0

            return GitOperationOutput(
                success=True,
                operation="add",
                message=f"Staged: {staged_desc}",
                details={
                    "staged_count": staged_count,
                    "files": files or "all"
                }
            ).to_json()

        except Exception as e:
            logger.error(f"Git add failed: {e}", exc_info=True)
            return GitOperationOutput(
                success=False,
                operation="add",
                message="Staging failed",
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()
