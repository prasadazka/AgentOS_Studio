"""Secrets management tools - .env file reading, cloud secret management"""

import subprocess
import shutil
import re
import json
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import ToolExecutionError, ErrorCode
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Type-Safe Models
# =============================================================================

class EnvSecret(BaseModel):
    """Represents a secret from .env file"""
    name: str
    has_value: bool = True
    is_sensitive: bool = False
    category: Optional[str] = None


class EnvFileResult(BaseModel):
    """Result of .env file reading"""
    success: bool
    file_path: str
    secrets_count: int = 0
    secrets: List[EnvSecret] = Field(default_factory=list)
    categories: Dict[str, List[str]] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class SecretManagerResult(BaseModel):
    """Result of secret manager operations"""
    success: bool
    operation: str
    project_id: Optional[str] = None
    secret_name: Optional[str] = None
    version: Optional[str] = None
    message: str = ""
    details: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Secret Pattern Detection
# =============================================================================

# Patterns that indicate sensitive secrets (never log values)
SENSITIVE_PATTERNS = [
    r".*PASSWORD.*",
    r".*SECRET.*",
    r".*KEY.*",
    r".*TOKEN.*",
    r".*CREDENTIAL.*",
    r".*PRIVATE.*",
    r".*AUTH.*",
    r".*API_KEY.*",
    r".*ACCESS_KEY.*",
    r".*SIGNING.*",
]

# Categories for organizing secrets
SECRET_CATEGORIES = {
    "database": [r".*DB.*", r".*DATABASE.*", r".*POSTGRES.*", r".*MYSQL.*", r".*MONGO.*", r".*REDIS.*"],
    "api_keys": [r".*API.*KEY.*", r".*API.*TOKEN.*"],
    "auth": [r".*AUTH.*", r".*JWT.*", r".*SESSION.*", r".*OAUTH.*"],
    "cloud": [r".*GCP.*", r".*AWS.*", r".*AZURE.*", r".*GOOGLE.*", r".*CLOUD.*"],
    "email": [r".*SMTP.*", r".*EMAIL.*", r".*MAIL.*", r".*SENDGRID.*"],
    "storage": [r".*S3.*", r".*BUCKET.*", r".*STORAGE.*"],
    "general": [r".*"],  # Catch-all
}


def is_sensitive(name: str) -> bool:
    """Check if secret name indicates sensitive data"""
    name_upper = name.upper()
    for pattern in SENSITIVE_PATTERNS:
        if re.match(pattern, name_upper):
            return True
    return False


def categorize_secret(name: str) -> str:
    """Categorize secret by name pattern"""
    name_upper = name.upper()
    for category, patterns in SECRET_CATEGORIES.items():
        if category == "general":
            continue
        for pattern in patterns:
            if re.match(pattern, name_upper):
                return category
    return "general"


# =============================================================================
# Env File Reader Tool
# =============================================================================

class EnvFileReaderTool(BaseTool):
    """Read .env file and extract secret names (NOT values)

    Features:
    - Parse .env files safely
    - Extract secret names only (never values)
    - Categorize secrets by type
    - Detect sensitive vs non-sensitive secrets
    - Support multiple env file formats

    Security:
    - NEVER returns actual secret values
    - Only returns names for planning deployment
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="env_file_reader",
                description="Read .env file and extract secret names (not values) for deployment planning",
                category="secrets",
                tags=["env", "secrets", "configuration", "deployment"]
            )
        )

    def _parse_env_file(self, content: str) -> List[Dict[str, Any]]:
        """Parse .env file content and extract variable names"""
        secrets = []
        lines = content.strip().split("\n")

        for line in lines:
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            # Handle export prefix
            if line.startswith("export "):
                line = line[7:]

            # Parse KEY=value
            if "=" in line:
                key = line.split("=", 1)[0].strip()

                # Skip if key is empty or invalid
                if not key or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
                    continue

                # Check if value exists (not empty)
                value_part = line.split("=", 1)[1].strip() if "=" in line else ""
                has_value = bool(value_part and value_part not in ['""', "''", ""])

                secrets.append({
                    "name": key,
                    "has_value": has_value,
                    "is_sensitive": is_sensitive(key),
                    "category": categorize_secret(key)
                })

        return secrets

    def _execute(
        self,
        env_path: str = ".env",
        project_path: str = "."
    ) -> str:
        """Read .env file and extract secret names

        Args:
            env_path: Path to .env file (relative to project_path or absolute)
            project_path: Base project directory

        Returns:
            JSON with secret names (NOT values)
        """
        try:
            project = Path(project_path).resolve()

            # Handle absolute vs relative path
            if Path(env_path).is_absolute():
                env_file = Path(env_path)
            else:
                env_file = project / env_path

            if not env_file.exists():
                # Check for common alternatives
                alternatives = [".env", ".env.local", ".env.example", ".env.sample"]
                found = None
                for alt in alternatives:
                    alt_path = project / alt
                    if alt_path.exists():
                        found = alt_path
                        break

                if found:
                    return EnvFileResult(
                        success=False,
                        file_path=str(env_file),
                        error=f"File not found: {env_file}. Found alternative: {found.name}",
                        warnings=[f"Consider using: {found.name}"],
                        error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                    ).to_json()

                return EnvFileResult(
                    success=False,
                    file_path=str(env_file),
                    error=f"Environment file not found: {env_file}",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

            # Read and parse file
            content = env_file.read_text(encoding="utf-8")
            secrets_data = self._parse_env_file(content)

            # Build categorized output
            secrets = []
            categories: Dict[str, List[str]] = {}
            warnings = []

            for s in secrets_data:
                secret = EnvSecret(
                    name=s["name"],
                    has_value=s["has_value"],
                    is_sensitive=s["is_sensitive"],
                    category=s["category"]
                )
                secrets.append(secret)

                # Add to categories
                cat = s["category"]
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append(s["name"])

                # Add warnings for empty values
                if not s["has_value"]:
                    warnings.append(f"Secret '{s['name']}' has no value set")

            logger.info(f"Parsed .env file: {len(secrets)} secrets found", extra={
                "file": str(env_file),
                "secrets_count": len(secrets),
                "categories": list(categories.keys())
            })

            return EnvFileResult(
                success=True,
                file_path=str(env_file),
                secrets_count=len(secrets),
                secrets=secrets,
                categories=categories,
                warnings=warnings
            ).to_json()

        except UnicodeDecodeError:
            return EnvFileResult(
                success=False,
                file_path=env_path,
                error="File is not valid UTF-8 text",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()

        except Exception as e:
            logger.error(f"Failed to read .env file: {e}", exc_info=True)
            return EnvFileResult(
                success=False,
                file_path=env_path,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


# =============================================================================
# GCP Secret Manager Tool
# =============================================================================

class GCPSecretManagerTool(BaseTool):
    """Manage secrets in Google Cloud Secret Manager

    Features:
    - Create, read, update, delete secrets
    - List secrets in project
    - Add secret versions
    - Access specific versions

    Requires:
    - gcloud CLI installed and authenticated
    - Secret Manager API enabled
    - Appropriate IAM permissions
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="gcp_secret_manager",
                description="Manage secrets in GCP Secret Manager (create, read, update, delete)",
                category="secrets",
                tags=["gcp", "secrets", "cloud", "deployment"],
                requires_auth=True
            )
        )
        self._gcloud_path = shutil.which("gcloud")

    def _run_gcloud(self, args: List[str], timeout: int = 60) -> subprocess.CompletedProcess:
        """Run gcloud command with Windows compatibility"""
        cmd = [self._gcloud_path or "gcloud"] + args
        if sys.platform == "win32":
            # Quote paths that contain spaces for Windows shell
            cmd_str = " ".join(f'"{c}"' if " " in c else c for c in cmd)
            return subprocess.run(cmd_str, shell=True, capture_output=True, text=True, timeout=timeout)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def _get_current_project(self) -> Optional[str]:
        """Get current GCP project from gcloud config"""
        try:
            result = self._run_gcloud(["config", "get-value", "project"])
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def _execute(
        self,
        action: str,
        secret_name: str,
        value: Optional[str] = None,
        project_id: Optional[str] = None,
        version: str = "latest"
    ) -> str:
        """Manage GCP secrets

        Args:
            action: Operation - 'create', 'get', 'set', 'delete', 'list'
            secret_name: Name of the secret
            value: Secret value (for create/set only)
            project_id: GCP project ID (default: current project)
            version: Secret version for 'get' (default: latest)

        Returns:
            JSON with operation result
        """
        try:
            if not self._gcloud_path:
                return SecretManagerResult(
                    success=False,
                    operation=action,
                    error="gcloud CLI not installed",
                    error_code=ErrorCode.TOOL_DEPENDENCY_MISSING.value
                ).to_json()

            # Get project ID
            project = project_id or self._get_current_project()
            if not project:
                return SecretManagerResult(
                    success=False,
                    operation=action,
                    error="No GCP project specified and no default project set",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

            action = action.lower()

            # List secrets
            if action == "list":
                result = self._run_gcloud([
                    "secrets", "list",
                    "--project", project,
                    "--format", "json"
                ])

                if result.returncode != 0:
                    return SecretManagerResult(
                        success=False,
                        operation="list",
                        project_id=project,
                        error=result.stderr.strip(),
                        error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                    ).to_json()

                try:
                    secrets = json.loads(result.stdout) if result.stdout else []
                    secret_names = [s.get("name", "").split("/")[-1] for s in secrets]
                except json.JSONDecodeError:
                    secret_names = []

                return SecretManagerResult(
                    success=True,
                    operation="list",
                    project_id=project,
                    message=f"Found {len(secret_names)} secrets",
                    details={"secrets": secret_names}
                ).to_json()

            # Create secret
            elif action == "create":
                if not value:
                    return SecretManagerResult(
                        success=False,
                        operation="create",
                        secret_name=secret_name,
                        error="Value is required for create operation",
                        error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                    ).to_json()

                # Create the secret
                create_result = self._run_gcloud([
                    "secrets", "create", secret_name,
                    "--project", project,
                    "--replication-policy", "automatic"
                ])

                if create_result.returncode != 0:
                    # Check if already exists
                    if "already exists" in create_result.stderr.lower():
                        pass  # Will add version below
                    else:
                        return SecretManagerResult(
                            success=False,
                            operation="create",
                            project_id=project,
                            secret_name=secret_name,
                            error=create_result.stderr.strip(),
                            error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                        ).to_json()

                # Add version with value (using echo pipe)
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
                    f.write(value)
                    temp_path = f.name

                try:
                    version_result = self._run_gcloud([
                        "secrets", "versions", "add", secret_name,
                        "--project", project,
                        "--data-file", temp_path
                    ])
                finally:
                    Path(temp_path).unlink(missing_ok=True)

                if version_result.returncode != 0:
                    return SecretManagerResult(
                        success=False,
                        operation="create",
                        project_id=project,
                        secret_name=secret_name,
                        error=version_result.stderr.strip(),
                        error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                    ).to_json()

                logger.info(f"Created secret: {secret_name}", extra={
                    "project": project,
                    "secret": secret_name
                })

                return SecretManagerResult(
                    success=True,
                    operation="create",
                    project_id=project,
                    secret_name=secret_name,
                    message=f"Secret '{secret_name}' created successfully"
                ).to_json()

            # Get secret value
            elif action == "get":
                result = self._run_gcloud([
                    "secrets", "versions", "access", version,
                    "--secret", secret_name,
                    "--project", project
                ])

                if result.returncode != 0:
                    return SecretManagerResult(
                        success=False,
                        operation="get",
                        project_id=project,
                        secret_name=secret_name,
                        error=result.stderr.strip(),
                        error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                    ).to_json()

                # Note: In production, be careful about logging/returning secret values
                return SecretManagerResult(
                    success=True,
                    operation="get",
                    project_id=project,
                    secret_name=secret_name,
                    version=version,
                    message="Secret retrieved successfully",
                    details={"value_length": len(result.stdout.strip())}
                ).to_json()

            # Set/Update secret value
            elif action == "set" or action == "update":
                if not value:
                    return SecretManagerResult(
                        success=False,
                        operation=action,
                        secret_name=secret_name,
                        error="Value is required for set/update operation",
                        error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                    ).to_json()

                # Add new version
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
                    f.write(value)
                    temp_path = f.name

                try:
                    result = self._run_gcloud([
                        "secrets", "versions", "add", secret_name,
                        "--project", project,
                        "--data-file", temp_path
                    ])
                finally:
                    Path(temp_path).unlink(missing_ok=True)

                if result.returncode != 0:
                    return SecretManagerResult(
                        success=False,
                        operation=action,
                        project_id=project,
                        secret_name=secret_name,
                        error=result.stderr.strip(),
                        error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                    ).to_json()

                return SecretManagerResult(
                    success=True,
                    operation=action,
                    project_id=project,
                    secret_name=secret_name,
                    message=f"Secret '{secret_name}' updated with new version"
                ).to_json()

            # Delete secret
            elif action == "delete":
                result = self._run_gcloud([
                    "secrets", "delete", secret_name,
                    "--project", project,
                    "--quiet"  # Skip confirmation
                ])

                if result.returncode != 0:
                    return SecretManagerResult(
                        success=False,
                        operation="delete",
                        project_id=project,
                        secret_name=secret_name,
                        error=result.stderr.strip(),
                        error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                    ).to_json()

                logger.info(f"Deleted secret: {secret_name}", extra={
                    "project": project,
                    "secret": secret_name
                })

                return SecretManagerResult(
                    success=True,
                    operation="delete",
                    project_id=project,
                    secret_name=secret_name,
                    message=f"Secret '{secret_name}' deleted successfully"
                ).to_json()

            else:
                return SecretManagerResult(
                    success=False,
                    operation=action,
                    error=f"Unknown action: {action}. Use: create, get, set, delete, list",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

        except subprocess.TimeoutExpired:
            return SecretManagerResult(
                success=False,
                operation=action,
                error="Command timed out",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()

        except Exception as e:
            logger.error(f"Secret manager operation failed: {e}", exc_info=True)
            return SecretManagerResult(
                success=False,
                operation=action,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


# =============================================================================
# Bulk Secret Sync Tool
# =============================================================================

class SecretSyncTool(BaseTool):
    """Sync secrets from .env file to cloud secret manager

    Features:
    - Read .env file
    - Create/update secrets in GCP Secret Manager
    - Skip unchanged secrets
    - Dry-run mode
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="secret_sync",
                description="Sync secrets from .env file to GCP Secret Manager",
                category="secrets",
                tags=["sync", "secrets", "deployment", "automation"],
                requires_auth=True
            )
        )
        self.env_reader = EnvFileReaderTool()
        self.secret_manager = GCPSecretManagerTool()

    def _execute(
        self,
        env_path: str = ".env",
        project_path: str = ".",
        project_id: Optional[str] = None,
        prefix: str = "",
        dry_run: bool = False
    ) -> str:
        """Sync .env secrets to GCP Secret Manager

        Args:
            env_path: Path to .env file
            project_path: Base project directory
            project_id: GCP project ID
            prefix: Prefix to add to secret names
            dry_run: If True, only show what would be synced

        Returns:
            JSON with sync results
        """
        try:
            # Read .env file
            env_result = json.loads(self.env_reader.execute(
                env_path=env_path,
                project_path=project_path
            ))

            if not env_result.get("success"):
                return json.dumps({
                    "success": False,
                    "error": f"Failed to read .env: {env_result.get('error')}",
                    "synced": 0
                }, indent=2)

            secrets = env_result.get("secrets", [])
            if not secrets:
                return json.dumps({
                    "success": True,
                    "message": "No secrets to sync",
                    "synced": 0
                }, indent=2)

            # Read actual values from .env
            env_file = Path(project_path).resolve() / env_path
            env_content = env_file.read_text(encoding="utf-8")
            env_values = {}

            for line in env_content.strip().split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    if line.startswith("export "):
                        line = line[7:]
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    env_values[key] = value

            synced = []
            failed = []
            skipped = []

            for secret in secrets:
                name = secret.get("name") or secret["name"]
                value = env_values.get(name)

                if not value:
                    skipped.append({"name": name, "reason": "no value"})
                    continue

                secret_name = f"{prefix}{name}" if prefix else name

                if dry_run:
                    synced.append({"name": secret_name, "action": "would_create"})
                    continue

                # Create/update secret
                result = json.loads(self.secret_manager.execute(
                    action="create",
                    secret_name=secret_name,
                    value=value,
                    project_id=project_id
                ))

                if result.get("success"):
                    synced.append({"name": secret_name, "action": "created"})
                else:
                    failed.append({"name": secret_name, "error": result.get("error")})

            logger.info(f"Secret sync complete: {len(synced)} synced, {len(failed)} failed")

            return json.dumps({
                "success": len(failed) == 0,
                "dry_run": dry_run,
                "total": len(secrets),
                "synced": len(synced),
                "failed": len(failed),
                "skipped": len(skipped),
                "details": {
                    "synced": synced,
                    "failed": failed,
                    "skipped": skipped
                }
            }, indent=2)

        except Exception as e:
            logger.error(f"Secret sync failed: {e}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": f"{type(e).__name__}: {str(e)}",
                "synced": 0
            }, indent=2)
