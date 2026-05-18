"""
Universal GCP CLI Executor Tool

Executes ANY gcloud command with safety checks and structured output.
"""

import subprocess
import json
import re
from typing import Dict, Any, Optional, List
from ..base import BaseTool, ToolMetadata
from agent_os.utils.logging import get_logger

# Constants
DEFAULT_TIMEOUT_SECONDS = 300  # 5 minutes
DEFAULT_OUTPUT_FORMAT = "json"
DANGEROUS_KEYWORDS = ['delete', 'destroy', 'remove']
CONFIRMATION_FLAGS = ['--force', '-q']
GCP_SDK_INSTALL_URL = "https://cloud.google.com/sdk/install"

logger = get_logger(__name__)


class GCPCLITool(BaseTool):
    """
    Execute any gcloud command with automatic error handling and output parsing.

    This is a UNIVERSAL tool - handles ALL GCP services:
    - Cloud SQL, AlloyDB, Spanner (databases)
    - VPC, Firewall, Load Balancers (networking)
    - Cloud Run, GKE, Compute Engine (compute)
    - Secret Manager, IAM, Service Accounts (security)
    - Storage, Artifact Registry (storage)

    Examples:
        # Create Cloud SQL
        execute_gcloud("sql instances create mydb --database-version=POSTGRES_15")

        # Create VPC
        execute_gcloud("compute networks create my-vpc --subnet-mode=custom")

        # Create AlloyDB cluster
        execute_gcloud("alloydb clusters create mycluster --region=us-central1")
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="execute_gcloud",
            description=(
                "Execute ANY gcloud CLI command. Supports all GCP services: "
                "Cloud SQL, VPC, AlloyDB, Cloud Run, IAM, Secrets, Storage, etc. "
                "Returns structured output (JSON when possible)."
            ),
            category="gcp"
        )
        super().__init__(metadata)

    def _execute(
        self,
        command: str,
        dry_run: bool = False,
        format: str = DEFAULT_OUTPUT_FORMAT,
        timeout: int = DEFAULT_TIMEOUT_SECONDS
    ) -> Dict[str, Any]:
        """
        Execute a gcloud command with safety checks and error handling.

        Args:
            command: gcloud command WITHOUT 'gcloud' prefix
                    Example: "sql instances create mydb --tier=db-f1-micro"
            dry_run: If True, only validates command without executing
            format: Output format (json, yaml, text). Defaults to 'json'
            timeout: Command timeout in seconds. Defaults to 300 (5 minutes)

        Returns:
            Dict containing:
                - success (bool): Whether command succeeded
                - output (Any): Parsed command output
                - error (str, optional): Error message if failed
                - command (str): Full command executed
                - auto_fix (str, optional): Suggested fix for common errors
                - exit_code (int, optional): Process exit code

        Raises:
            ValueError: If command is empty or invalid
        """
        # Validate inputs
        self._validate_command(command)
        self._validate_timeout(timeout)
        self._validate_format(format)

        # Check for destructive operations
        if self._is_destructive_command(command, dry_run):
            return self._create_destructive_command_error(command)

        # Build full command
        full_command = self._build_full_command(command, format)

        # Dry run validation
        if dry_run:
            logger.info(f"Dry run mode: {full_command}")
            return self._create_dry_run_response(full_command)

        # Execute command
        try:
            return self._execute_command(full_command, format, timeout)
        except subprocess.TimeoutExpired:
            logger.error(f"Command timeout after {timeout}s: {full_command}")
            return self._create_timeout_error(full_command, timeout)
        except FileNotFoundError:
            logger.error("gcloud CLI not found")
            return self._create_cli_not_found_error(full_command)
        except Exception as e:
            logger.error(f"Command execution failed: {e}", exc_info=True)
            return self._create_execution_error(full_command, e)

    def _validate_command(self, command: str) -> None:
        """Validate command input."""
        if not command or not command.strip():
            raise ValueError("Command cannot be empty")
        if command.strip().startswith("gcloud"):
            raise ValueError("Command should not include 'gcloud' prefix")

    def _validate_timeout(self, timeout: int) -> None:
        """Validate timeout value."""
        if timeout <= 0:
            raise ValueError(f"Timeout must be positive, got {timeout}")
        if timeout > 3600:  # 1 hour max
            raise ValueError(f"Timeout cannot exceed 3600 seconds, got {timeout}")

    def _validate_format(self, format: str) -> None:
        """Validate output format."""
        valid_formats = ["json", "yaml", "text", "csv", "table"]
        if format not in valid_formats:
            raise ValueError(f"Invalid format '{format}'. Must be one of: {valid_formats}")

    def _is_destructive_command(self, command: str, dry_run: bool) -> bool:
        """Check if command is destructive and requires confirmation."""
        if dry_run:
            return False

        command_lower = command.lower()
        has_dangerous_keyword = any(keyword in command_lower for keyword in DANGEROUS_KEYWORDS)
        has_confirmation = any(flag in command for flag in CONFIRMATION_FLAGS)

        return has_dangerous_keyword and not has_confirmation

    def _create_destructive_command_error(self, command: str) -> Dict[str, Any]:
        """Create error response for unconfirmed destructive command."""
        return {
            "success": False,
            "error": "Destructive command requires --force or -q flag for confirmation",
            "command": command,
            "suggestion": f"Add --force to confirm: gcloud {command} --force"
        }

    def _build_full_command(self, command: str, format: str) -> str:
        """Build full gcloud command with format flag."""
        full_command = f"gcloud {command}"

        # Add format flag if not already present and format is not 'text'
        if '--format' not in command and format != 'text':
            full_command += f" --format={format}"

        return full_command

    def _create_dry_run_response(self, full_command: str) -> Dict[str, Any]:
        """Create response for dry run mode."""
        return {
            "success": True,
            "output": f"DRY RUN: Would execute: {full_command}",
            "command": full_command,
            "dry_run": True
        }

    def _execute_command(
        self,
        full_command: str,
        format: str,
        timeout: int
    ) -> Dict[str, Any]:
        """Execute gcloud command and parse output."""
        logger.info(f"Executing: {full_command}")

        result = subprocess.run(
            full_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        output = result.stdout.strip()
        error_output = result.stderr.strip()

        # Parse output based on format
        parsed_output = self._parse_output(output, format)

        if result.returncode == 0:
            logger.info(f"Command succeeded: {full_command}")
            return self._create_success_response(full_command, parsed_output, output)
        else:
            logger.warning(f"Command failed with exit code {result.returncode}: {full_command}")
            return self._create_error_response(
                full_command,
                error_output,
                parsed_output,
                result.returncode
            )

    def _parse_output(self, output: str, format: str) -> Any:
        """Parse command output based on format."""
        if not output:
            return None

        if format == 'json':
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                logger.debug("Failed to parse JSON output, returning as string")
                return output

        return output

    def _create_success_response(
        self,
        command: str,
        parsed_output: Any,
        raw_output: str
    ) -> Dict[str, Any]:
        """Create success response."""
        return {
            "success": True,
            "output": parsed_output,
            "raw_output": raw_output,
            "command": command,
            "exit_code": 0
        }

    def _create_error_response(
        self,
        command: str,
        error_msg: str,
        parsed_output: Any,
        exit_code: int
    ) -> Dict[str, Any]:
        """Create error response with auto-fix suggestions."""
        error_msg = error_msg or "Command failed"
        auto_fix = self._detect_auto_fix(error_msg)

        response = {
            "success": False,
            "error": error_msg,
            "command": command,
            "exit_code": exit_code
        }

        if parsed_output:
            response["output"] = parsed_output

        if auto_fix:
            response["auto_fix"] = auto_fix

        return response

    def _detect_auto_fix(self, error_msg: str) -> Optional[str]:
        """Detect common errors and suggest fixes."""
        # API not enabled
        if "not enabled" in error_msg or "not been used" in error_msg:
            api_match = re.search(r'\[(.*?)\]', error_msg)
            if api_match:
                return f"gcloud services enable {api_match.group(1)}"

        # Permission denied
        if "permission" in error_msg.lower() or "forbidden" in error_msg.lower():
            return "Check IAM permissions with: gcloud projects get-iam-policy PROJECT_ID"

        # Project not found
        if "not found" in error_msg.lower() and "project" in error_msg.lower():
            return "List projects with: gcloud projects list"

        return None

    def _create_timeout_error(self, command: str, timeout: int) -> Dict[str, Any]:
        """Create timeout error response."""
        return {
            "success": False,
            "error": f"Command timeout after {timeout} seconds",
            "command": command,
            "suggestion": f"Increase timeout or check command: {command}"
        }

    def _create_cli_not_found_error(self, command: str) -> Dict[str, Any]:
        """Create CLI not found error response."""
        return {
            "success": False,
            "error": "gcloud CLI not found. Please install Google Cloud SDK.",
            "command": command,
            "suggestion": f"Install from: {GCP_SDK_INSTALL_URL}"
        }

    def _create_execution_error(self, command: str, exception: Exception) -> Dict[str, Any]:
        """Create general execution error response."""
        return {
            "success": False,
            "error": f"Execution failed: {str(exception)}",
            "command": command,
            "exception_type": type(exception).__name__
        }


class GCPAPIClientTool(BaseTool):
    """
    Direct GCP API client for operations not available via gcloud CLI.

    Uses Google Cloud Python client libraries to call ANY GCP API.
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="call_gcp_api",
            description=(
                "Call any GCP API directly using Python client libraries. "
                "Use when gcloud CLI is insufficient or for programmatic access. "
                "Supports: Compute, Storage, BigQuery, Pub/Sub, Datastore, etc."
            ),
            category="gcp"
        )
        super().__init__(metadata)

    def _execute(
        self,
        service: str,
        method: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Call a GCP API method.

        Args:
            service: GCP service name (compute, storage, bigquery, etc.)
            method: API method to call (e.g., instances.insert)
            params: Method parameters as dictionary

        Returns:
            API response as dictionary
        """
        try:
            # Import appropriate client
            if service == "compute":
                from google.cloud import compute_v1
                # Dynamic method calling based on params
                pass
            elif service == "storage":
                from google.cloud import storage
                pass
            elif service == "secretmanager":
                from google.cloud import secretmanager
                pass
            # ... more services

            return {
                "success": True,
                "output": "API client implementation pending - use execute_gcloud for now",
                "service": service,
                "method": method
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"API call failed: {str(e)}",
                "service": service,
                "method": method
            }


class TerraformExecutorTool(BaseTool):
    """
    Execute Terraform for infrastructure-as-code deployments.

    Allows declaring infrastructure in HCL and provisioning it atomically.
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="execute_terraform",
            description=(
                "Execute Terraform commands for infrastructure-as-code. "
                "Supports plan, apply, destroy operations. "
                "Best for complex multi-resource provisioning."
            ),
            category="iac"
        )
        super().__init__(metadata)

    def _execute(
        self,
        terraform_code: str,
        action: str = "plan",
        working_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute Terraform.

        Args:
            terraform_code: Terraform HCL code
            action: Terraform action (init, plan, apply, destroy)
            working_dir: Directory to execute in

        Returns:
            Terraform output
        """
        # This would write terraform_code to a .tf file
        # Then run terraform init/plan/apply

        return {
            "success": True,
            "output": "Terraform execution pending - Phase 2 feature",
            "action": action
        }
