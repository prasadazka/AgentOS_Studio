"""Git initialization and GitHub repository management tools"""

import subprocess
import os
import json
import shutil
from typing import Optional, Dict, Any, List
from pydantic import Field

from agent_os.tools.base import BaseTool, ToolMetadata


def _find_gh_executable() -> Optional[str]:
    """Find gh executable on the system"""
    # Try shutil.which first (checks PATH)
    gh_path = shutil.which("gh")
    if gh_path:
        return gh_path

    # Common Windows installation paths
    if os.name == "nt":
        common_paths = [
            r"C:\Program Files\GitHub CLI\gh.exe",
            r"C:\Program Files (x86)\GitHub CLI\gh.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\GitHub CLI\gh.exe"),
            os.path.expanduser(r"~\scoop\apps\gh\current\bin\gh.exe"),
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path

    # Common Unix paths
    else:
        common_paths = [
            "/usr/bin/gh",
            "/usr/local/bin/gh",
            os.path.expanduser("~/.local/bin/gh"),
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path

    return None


class GitInitTool(BaseTool):
    """
    Initialize a Git repository in a local directory.

    Detects if git repo exists, creates one if not, and sets up initial configuration.
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="git_init",
            description="Initialize a git repository in a directory. Detects if repo exists, creates if not.",
            category="git"
        )
        super().__init__(metadata)

    def _execute(
        self,
        path: str,
        initial_branch: str = "main",
        user_name: Optional[str] = None,
        user_email: Optional[str] = None,
        create_gitignore: bool = True,
        gitignore_template: str = "python"
    ) -> Dict[str, Any]:
        """
        Initialize git repository.

        Args:
            path: Directory path to initialize
            initial_branch: Name of the initial branch (default: main)
            user_name: Git user name for this repo (optional)
            user_email: Git user email for this repo (optional)
            create_gitignore: Whether to create a .gitignore file
            gitignore_template: Template for gitignore (python, node, go, java)

        Returns:
            Dict with initialization status and details
        """
        # Normalize path
        path = os.path.abspath(os.path.expanduser(path))

        if not os.path.exists(path):
            return {
                "success": False,
                "error": f"Directory does not exist: {path}",
                "action_required": "create_directory",
                "message": f"The directory '{path}' does not exist. Would you like to create it?"
            }

        git_dir = os.path.join(path, ".git")

        # Check if git repo already exists
        if os.path.exists(git_dir):
            # Get current branch and status
            try:
                branch = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=path, capture_output=True, text=True
                ).stdout.strip()

                remote = subprocess.run(
                    ["git", "remote", "-v"],
                    cwd=path, capture_output=True, text=True
                ).stdout.strip()

                return {
                    "success": True,
                    "already_initialized": True,
                    "path": path,
                    "current_branch": branch,
                    "has_remote": bool(remote),
                    "remote_info": remote if remote else None,
                    "message": f"Git repository already exists at '{path}' on branch '{branch}'."
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Git directory exists but is corrupted: {str(e)}",
                    "action_required": "repair_or_reinitialize"
                }

        # Initialize new repository
        try:
            # git init with initial branch
            result = subprocess.run(
                ["git", "init", "-b", initial_branch],
                cwd=path, capture_output=True, text=True
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Failed to initialize git: {result.stderr}"
                }

            # Configure user if provided
            if user_name:
                subprocess.run(
                    ["git", "config", "user.name", user_name],
                    cwd=path, capture_output=True
                )

            if user_email:
                subprocess.run(
                    ["git", "config", "user.email", user_email],
                    cwd=path, capture_output=True
                )

            # Create .gitignore if requested
            gitignore_path = os.path.join(path, ".gitignore")
            if create_gitignore and not os.path.exists(gitignore_path):
                gitignore_content = self._get_gitignore_template(gitignore_template)
                with open(gitignore_path, "w") as f:
                    f.write(gitignore_content)

            return {
                "success": True,
                "already_initialized": False,
                "path": path,
                "branch": initial_branch,
                "gitignore_created": create_gitignore,
                "message": f"Successfully initialized git repository at '{path}' with branch '{initial_branch}'.",
                "next_steps": [
                    "Add files with 'git add .'",
                    "Create initial commit with 'git commit -m \"Initial commit\"'",
                    "Create remote repository on GitHub",
                    "Add remote with 'git remote add origin <url>'",
                    "Push with 'git push -u origin main'"
                ]
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to initialize repository: {str(e)}"
            }

    def _get_gitignore_template(self, template: str) -> str:
        """Get gitignore content based on template type."""
        templates = {
            "python": """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
.env
.venv
env/
venv/
ENV/

# IDE
.idea/
.vscode/
*.swp
*.swo

# Testing
.coverage
htmlcov/
.pytest_cache/

# Secrets
.env.local
.env.*.local
secrets.yaml
credentials.json
*.pem
*.key
""",
            "node": """# Node
node_modules/
npm-debug.log
yarn-error.log
.npm
.yarn

# Build
dist/
build/
.next/

# Environment
.env
.env.local
.env.*.local

# IDE
.idea/
.vscode/

# Testing
coverage/
""",
            "go": """# Go
*.exe
*.exe~
*.dll
*.so
*.dylib
*.test
*.out
vendor/
go.work

# IDE
.idea/
.vscode/

# Environment
.env
""",
            "java": """# Java
*.class
*.jar
*.war
*.ear
target/
.gradle/
build/

# IDE
.idea/
*.iml
.vscode/

# Environment
.env
"""
        }
        return templates.get(template, templates["python"])


class GitHubRepoTool(BaseTool):
    """
    Create and manage GitHub repositories.

    Uses GitHub CLI (gh) for operations.
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="github_repo_create",
            description="Create a new GitHub repository and optionally link it to local repo.",
            category="git",
            requires_auth=True
        )
        super().__init__(metadata)

    def _execute(
        self,
        name: str,
        description: str = "",
        visibility: str = "private",
        local_path: Optional[str] = None,
        add_remote: bool = True,
        push_initial: bool = False,
        organization: Optional[str] = None,
        enable_issues: bool = True,
        enable_wiki: bool = False,
        gitignore_template: Optional[str] = None,
        license_template: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a GitHub repository.

        Args:
            name: Repository name
            description: Repository description
            visibility: public, private, or internal
            local_path: Local git repo path to link
            add_remote: Whether to add as remote to local repo
            push_initial: Whether to push initial commit
            organization: GitHub organization (uses personal account if not specified)
            enable_issues: Enable issues
            enable_wiki: Enable wiki
            gitignore_template: Gitignore template name
            license_template: License template (mit, apache-2.0, gpl-3.0, etc.)

        Returns:
            Dict with repository creation status and URL
        """
        # Find gh CLI executable
        gh_exe = _find_gh_executable()
        if not gh_exe:
            return {
                "success": False,
                "error": "GitHub CLI (gh) not found in PATH or common install locations.",
                "action_required": "install_gh_cli",
                "instructions": "Install GitHub CLI: https://cli.github.com/"
            }

        # Check if gh CLI is available
        try:
            gh_check = subprocess.run(
                [gh_exe, "--version"],
                capture_output=True, text=True
            )
            if gh_check.returncode != 0:
                return {
                    "success": False,
                    "error": "GitHub CLI (gh) failed to run.",
                    "action_required": "check_gh_cli",
                    "instructions": f"gh found at {gh_exe} but failed to run"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"GitHub CLI error: {str(e)}",
                "action_required": "check_gh_cli"
            }

        # Check authentication
        auth_check = subprocess.run(
            [gh_exe, "auth", "status"],
            capture_output=True, text=True
        )
        if auth_check.returncode != 0:
            return {
                "success": False,
                "error": "Not authenticated with GitHub CLI.",
                "action_required": "authenticate",
                "instructions": "Run 'gh auth login' to authenticate."
            }

        # Build create command
        cmd = [gh_exe, "repo", "create", name]

        if organization:
            cmd = [gh_exe, "repo", "create", f"{organization}/{name}"]

        cmd.extend(["--" + visibility])

        if description:
            cmd.extend(["--description", description])

        if enable_issues:
            cmd.append("--enable-issues")

        if enable_wiki:
            cmd.append("--enable-wiki")

        if gitignore_template:
            cmd.extend(["--gitignore", gitignore_template])

        if license_template:
            cmd.extend(["--license", license_template])

        # Create the repository
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip()
                if "already exists" in error_msg.lower():
                    return {
                        "success": False,
                        "error": f"Repository '{name}' already exists.",
                        "action_required": "use_existing_or_rename"
                    }
                return {
                    "success": False,
                    "error": f"Failed to create repository: {error_msg}"
                }

            # Get repository URL
            repo_full_name = f"{organization}/{name}" if organization else name
            repo_url = f"https://github.com/{repo_full_name}" if organization else result.stdout.strip()

            # If no URL in output, fetch it
            if not repo_url or not repo_url.startswith("http"):
                view_result = subprocess.run(
                    [gh_exe, "repo", "view", name, "--json", "url"],
                    capture_output=True, text=True
                )
                if view_result.returncode == 0:
                    repo_data = json.loads(view_result.stdout)
                    repo_url = repo_data.get("url", "")

            response = {
                "success": True,
                "repository_name": name,
                "repository_url": repo_url,
                "visibility": visibility,
                "message": f"Successfully created repository '{name}'."
            }

            # Link to local repo if specified
            if local_path and add_remote:
                local_path = os.path.abspath(os.path.expanduser(local_path))

                if not os.path.exists(os.path.join(local_path, ".git")):
                    response["remote_added"] = False
                    response["warning"] = f"Local path '{local_path}' is not a git repository. Initialize it first."
                else:
                    # Add remote
                    remote_url = f"https://github.com/{repo_full_name}.git" if organization else f"{repo_url}.git"

                    # Check if origin already exists
                    remote_check = subprocess.run(
                        ["git", "remote", "get-url", "origin"],
                        cwd=local_path, capture_output=True, text=True
                    )

                    if remote_check.returncode == 0:
                        # Remote exists, update it
                        subprocess.run(
                            ["git", "remote", "set-url", "origin", remote_url],
                            cwd=local_path, capture_output=True
                        )
                        response["remote_action"] = "updated"
                    else:
                        # Add new remote
                        subprocess.run(
                            ["git", "remote", "add", "origin", remote_url],
                            cwd=local_path, capture_output=True
                        )
                        response["remote_action"] = "added"

                    response["remote_added"] = True
                    response["remote_url"] = remote_url

                    # Push initial commit if requested
                    if push_initial:
                        # Check if there are commits
                        log_check = subprocess.run(
                            ["git", "log", "-1"],
                            cwd=local_path, capture_output=True, text=True
                        )

                        if log_check.returncode == 0:
                            # Get current branch
                            branch = subprocess.run(
                                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                                cwd=local_path, capture_output=True, text=True
                            ).stdout.strip()

                            push_result = subprocess.run(
                                ["git", "push", "-u", "origin", branch],
                                cwd=local_path, capture_output=True, text=True
                            )

                            if push_result.returncode == 0:
                                response["pushed"] = True
                                response["branch"] = branch
                            else:
                                response["pushed"] = False
                                response["push_error"] = push_result.stderr.strip()
                        else:
                            response["pushed"] = False
                            response["push_error"] = "No commits to push. Create an initial commit first."

            response["next_steps"] = []
            if not local_path:
                response["next_steps"].append(f"Clone: git clone {repo_url}")
            elif not response.get("remote_added"):
                response["next_steps"].append(f"Add remote: git remote add origin {repo_url}.git")
            if not response.get("pushed"):
                response["next_steps"].append("Push code: git push -u origin main")
            response["next_steps"].append("Set up CI/CD and secrets")

            return response

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to create repository: {str(e)}"
            }


class GitHubSecretsTool(BaseTool):
    """
    Manage GitHub repository secrets for CI/CD.

    Supports repository secrets, environment secrets, and organization secrets.
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="github_secrets",
            description="Manage GitHub repository secrets for CI/CD pipelines.",
            category="git",
            requires_auth=True
        )
        super().__init__(metadata)

    def _execute(
        self,
        action: str,
        repository: str,
        secret_name: Optional[str] = None,
        secret_value: Optional[str] = None,
        secrets_from_env: Optional[str] = None,
        environment: Optional[str] = None,
        organization: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Manage GitHub secrets.

        Args:
            action: list, set, delete, or sync_from_env
            repository: Repository name (owner/repo or just repo)
            secret_name: Name of the secret (for set/delete)
            secret_value: Value of the secret (for set)
            secrets_from_env: Path to .env file to sync secrets from
            environment: GitHub environment name (for environment secrets)
            organization: Organization name (for org secrets)

        Returns:
            Dict with operation status
        """
        # Find gh CLI executable
        gh_exe = _find_gh_executable()
        if not gh_exe:
            return {
                "success": False,
                "error": "GitHub CLI (gh) not found.",
                "action_required": "install_gh_cli"
            }

        # Check gh CLI
        try:
            subprocess.run([gh_exe, "--version"], capture_output=True, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            return {
                "success": False,
                "error": "GitHub CLI (gh) is not installed or not working.",
                "action_required": "install_gh_cli"
            }

        # Check authentication
        auth_check = subprocess.run(
            [gh_exe, "auth", "status"],
            capture_output=True, text=True
        )
        if auth_check.returncode != 0:
            return {
                "success": False,
                "error": "Not authenticated with GitHub CLI.",
                "action_required": "authenticate"
            }

        # Store gh_exe for use in helper methods
        self._gh_exe = gh_exe

        if action == "list":
            return self._list_secrets(repository, environment, organization)
        elif action == "set":
            if not secret_name or not secret_value:
                return {
                    "success": False,
                    "error": "secret_name and secret_value are required for 'set' action."
                }
            return self._set_secret(repository, secret_name, secret_value, environment, organization)
        elif action == "delete":
            if not secret_name:
                return {
                    "success": False,
                    "error": "secret_name is required for 'delete' action."
                }
            return self._delete_secret(repository, secret_name, environment, organization)
        elif action == "sync_from_env":
            if not secrets_from_env:
                return {
                    "success": False,
                    "error": "secrets_from_env path is required for 'sync_from_env' action."
                }
            return self._sync_from_env(repository, secrets_from_env, environment, organization)
        else:
            return {
                "success": False,
                "error": f"Unknown action: {action}. Use list, set, delete, or sync_from_env."
            }

    def _list_secrets(
        self,
        repository: str,
        environment: Optional[str] = None,
        organization: Optional[str] = None
    ) -> Dict[str, Any]:
        """List secrets in repository."""
        cmd = [self._gh_exe, "secret", "list", "-R", repository]

        if environment:
            cmd.extend(["--env", environment])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Failed to list secrets: {result.stderr.strip()}"
                }

            # Parse output
            secrets = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split("\t")
                    if parts:
                        secrets.append({
                            "name": parts[0],
                            "updated_at": parts[1] if len(parts) > 1 else "unknown"
                        })

            return {
                "success": True,
                "repository": repository,
                "environment": environment,
                "secrets": secrets,
                "count": len(secrets),
                "message": f"Found {len(secrets)} secrets in repository."
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to list secrets: {str(e)}"
            }

    def _set_secret(
        self,
        repository: str,
        secret_name: str,
        secret_value: str,
        environment: Optional[str] = None,
        organization: Optional[str] = None
    ) -> Dict[str, Any]:
        """Set a secret in repository."""
        cmd = [self._gh_exe, "secret", "set", secret_name, "-R", repository]

        if environment:
            cmd.extend(["--env", environment])

        try:
            # Use stdin to pass secret value securely
            result = subprocess.run(
                cmd,
                input=secret_value,
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Failed to set secret: {result.stderr.strip()}"
                }

            return {
                "success": True,
                "repository": repository,
                "secret_name": secret_name,
                "environment": environment,
                "message": f"Successfully set secret '{secret_name}' in repository."
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to set secret: {str(e)}"
            }

    def _delete_secret(
        self,
        repository: str,
        secret_name: str,
        environment: Optional[str] = None,
        organization: Optional[str] = None
    ) -> Dict[str, Any]:
        """Delete a secret from repository."""
        cmd = [self._gh_exe, "secret", "delete", secret_name, "-R", repository]

        if environment:
            cmd.extend(["--env", environment])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Failed to delete secret: {result.stderr.strip()}"
                }

            return {
                "success": True,
                "repository": repository,
                "secret_name": secret_name,
                "message": f"Successfully deleted secret '{secret_name}' from repository."
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to delete secret: {str(e)}"
            }

    def _sync_from_env(
        self,
        repository: str,
        env_file_path: str,
        environment: Optional[str] = None,
        organization: Optional[str] = None
    ) -> Dict[str, Any]:
        """Sync secrets from .env file to GitHub."""
        env_file_path = os.path.abspath(os.path.expanduser(env_file_path))

        if not os.path.exists(env_file_path):
            return {
                "success": False,
                "error": f"Environment file not found: {env_file_path}"
            }

        # Read and parse .env file
        secrets_to_sync = []
        try:
            with open(env_file_path, "r") as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith("#"):
                        continue

                    # Parse KEY=VALUE
                    if "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")

                        if key and value:
                            secrets_to_sync.append({"name": key, "value": value})
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to read .env file: {str(e)}"
            }

        if not secrets_to_sync:
            return {
                "success": False,
                "error": "No secrets found in .env file."
            }

        # Sync each secret
        synced = []
        failed = []

        for secret in secrets_to_sync:
            result = self._set_secret(
                repository=repository,
                secret_name=secret["name"],
                secret_value=secret["value"],
                environment=environment,
                organization=organization
            )

            if result["success"]:
                synced.append(secret["name"])
            else:
                failed.append({
                    "name": secret["name"],
                    "error": result.get("error", "Unknown error")
                })

        return {
            "success": len(failed) == 0,
            "repository": repository,
            "environment": environment,
            "synced_secrets": synced,
            "failed_secrets": failed,
            "total": len(secrets_to_sync),
            "synced_count": len(synced),
            "failed_count": len(failed),
            "message": f"Synced {len(synced)}/{len(secrets_to_sync)} secrets to repository."
        }


class GitBranchCreateTool(BaseTool):
    """
    Create and manage Git branches.
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="git_branch_create",
            description="Create, switch, and manage git branches.",
            category="git"
        )
        super().__init__(metadata)

    def _execute(
        self,
        path: str,
        action: str = "create",
        branch_name: Optional[str] = None,
        from_branch: Optional[str] = None,
        push_remote: bool = False
    ) -> Dict[str, Any]:
        """
        Manage git branches.

        Args:
            path: Local repository path
            action: create, switch, list, delete
            branch_name: Branch name (for create/switch/delete)
            from_branch: Base branch to create from
            push_remote: Push new branch to remote

        Returns:
            Dict with operation status
        """
        path = os.path.abspath(os.path.expanduser(path))

        if not os.path.exists(os.path.join(path, ".git")):
            return {
                "success": False,
                "error": f"Not a git repository: {path}"
            }

        if action == "list":
            return self._list_branches(path)
        elif action == "create":
            if not branch_name:
                return {"success": False, "error": "branch_name is required for 'create'"}
            return self._create_branch(path, branch_name, from_branch, push_remote)
        elif action == "switch":
            if not branch_name:
                return {"success": False, "error": "branch_name is required for 'switch'"}
            return self._switch_branch(path, branch_name)
        elif action == "delete":
            if not branch_name:
                return {"success": False, "error": "branch_name is required for 'delete'"}
            return self._delete_branch(path, branch_name)
        else:
            return {
                "success": False,
                "error": f"Unknown action: {action}. Use create, switch, list, or delete."
            }

    def _list_branches(self, path: str) -> Dict[str, Any]:
        """List all branches."""
        try:
            result = subprocess.run(
                ["git", "branch", "-a", "-v"],
                cwd=path, capture_output=True, text=True
            )

            branches = []
            current_branch = None

            for line in result.stdout.strip().split("\n"):
                if line:
                    is_current = line.startswith("*")
                    branch_info = line.lstrip("* ").strip()
                    parts = branch_info.split()
                    if parts:
                        branch_name = parts[0]
                        branches.append(branch_name)
                        if is_current:
                            current_branch = branch_name

            return {
                "success": True,
                "branches": branches,
                "current_branch": current_branch,
                "count": len(branches)
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _create_branch(
        self,
        path: str,
        branch_name: str,
        from_branch: Optional[str],
        push_remote: bool
    ) -> Dict[str, Any]:
        """Create a new branch."""
        try:
            # Checkout base branch if specified
            if from_branch:
                subprocess.run(
                    ["git", "checkout", from_branch],
                    cwd=path, capture_output=True, check=True
                )

            # Create and switch to new branch
            result = subprocess.run(
                ["git", "checkout", "-b", branch_name],
                cwd=path, capture_output=True, text=True
            )

            if result.returncode != 0:
                if "already exists" in result.stderr:
                    return {
                        "success": False,
                        "error": f"Branch '{branch_name}' already exists.",
                        "action_required": "switch_or_rename"
                    }
                return {"success": False, "error": result.stderr.strip()}

            response = {
                "success": True,
                "branch_name": branch_name,
                "from_branch": from_branch,
                "message": f"Created and switched to branch '{branch_name}'."
            }

            # Push to remote if requested
            if push_remote:
                push_result = subprocess.run(
                    ["git", "push", "-u", "origin", branch_name],
                    cwd=path, capture_output=True, text=True
                )

                if push_result.returncode == 0:
                    response["pushed_to_remote"] = True
                else:
                    response["pushed_to_remote"] = False
                    response["push_error"] = push_result.stderr.strip()

            return response

        except subprocess.CalledProcessError as e:
            return {"success": False, "error": str(e)}

    def _switch_branch(self, path: str, branch_name: str) -> Dict[str, Any]:
        """Switch to a branch."""
        try:
            result = subprocess.run(
                ["git", "checkout", branch_name],
                cwd=path, capture_output=True, text=True
            )

            if result.returncode != 0:
                return {"success": False, "error": result.stderr.strip()}

            return {
                "success": True,
                "branch_name": branch_name,
                "message": f"Switched to branch '{branch_name}'."
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _delete_branch(self, path: str, branch_name: str) -> Dict[str, Any]:
        """Delete a branch."""
        try:
            result = subprocess.run(
                ["git", "branch", "-d", branch_name],
                cwd=path, capture_output=True, text=True
            )

            if result.returncode != 0:
                # Try force delete
                if "not fully merged" in result.stderr:
                    return {
                        "success": False,
                        "error": f"Branch '{branch_name}' is not fully merged.",
                        "action_required": "force_delete_or_merge",
                        "force_command": f"git branch -D {branch_name}"
                    }
                return {"success": False, "error": result.stderr.strip()}

            return {
                "success": True,
                "branch_name": branch_name,
                "message": f"Deleted branch '{branch_name}'."
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


class GitHubRepoListTool(BaseTool):
    """
    List GitHub repositories for the authenticated user.
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="github_repo_list",
            description="List GitHub repositories for the authenticated user.",
            category="git",
            requires_auth=True
        )
        super().__init__(metadata)

    def _execute(
        self,
        limit: int = 30,
        visibility: str = "all",
        sort: str = "updated"
    ) -> Dict[str, Any]:
        """
        List GitHub repositories.

        Args:
            limit: Maximum number of repos to list
            visibility: all, public, or private
            sort: updated, created, pushed, full_name

        Returns:
            Dict with list of repositories
        """
        gh_exe = _find_gh_executable()
        if not gh_exe:
            return {
                "success": False,
                "error": "GitHub CLI (gh) not found."
            }

        try:
            cmd = [gh_exe, "repo", "list", "--limit", str(limit), "--json", "name,url,isPrivate,updatedAt"]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Failed to list repos: {result.stderr.strip()}"
                }

            repos = json.loads(result.stdout)

            return {
                "success": True,
                "count": len(repos),
                "repositories": [
                    {
                        "name": r["name"],
                        "url": r["url"],
                        "private": r["isPrivate"],
                        "updated": r["updatedAt"]
                    }
                    for r in repos
                ]
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


class GitRemoteTool(BaseTool):
    """
    Get remote URL for a git repository.
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="git_remote",
            description="Get the remote origin URL for a git repository.",
            category="git"
        )
        super().__init__(metadata)

    def _execute(self, path: str) -> Dict[str, Any]:
        """
        Get remote origin URL.

        Args:
            path: Path to the git repository

        Returns:
            Dict with remote URL info
        """
        path = os.path.abspath(os.path.expanduser(path))

        if not os.path.exists(os.path.join(path, ".git")):
            return {
                "success": False,
                "error": f"Not a git repository: {path}"
            }

        try:
            result = subprocess.run(
                ["git", "remote", "-v"],
                cwd=path, capture_output=True, text=True
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Failed to get remotes: {result.stderr.strip()}"
                }

            remotes = {}
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split()
                    if len(parts) >= 2:
                        name = parts[0]
                        url = parts[1]
                        remotes[name] = url

            origin_url = remotes.get("origin", "")

            return {
                "success": True,
                "path": path,
                "origin_url": origin_url,
                "all_remotes": remotes,
                "has_remote": bool(origin_url)
            }

        except Exception as e:
            return {"success": False, "error": str(e)}
