"""
Google Cloud Platform (GCP) Tools for Agent_OS

Provides production-grade GCP integrations:
- Cloud Storage (gs://) operations
- BigQuery queries and dataset management
- Compute Engine VM management
- IAM and resource management

Uses gcloud CLI internally with ShellExecutorTool for security.
"""

import json
import re
from typing import Optional, Dict, Any, List
from enum import Enum
from pydantic import BaseModel, Field

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.tools.library.shell import SafeShellExecutorTool, ApprovalShellExecutorTool, ShellExecutor, OSType
from agent_os.tools.approval import ApprovalManager, ApprovalMode
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# GCP Configuration
# =============================================================================

class GCPRegion(str, Enum):
    """Common GCP regions"""
    US_CENTRAL1 = "us-central1"
    US_EAST1 = "us-east1"
    US_WEST1 = "us-west1"
    EUROPE_WEST1 = "europe-west1"
    EUROPE_WEST2 = "europe-west2"
    ASIA_EAST1 = "asia-east1"
    ASIA_SOUTHEAST1 = "asia-southeast1"


class GCPMachineType(str, Enum):
    """Common GCP machine types"""
    E2_MICRO = "e2-micro"
    E2_SMALL = "e2-small"
    E2_MEDIUM = "e2-medium"
    N1_STANDARD_1 = "n1-standard-1"
    N1_STANDARD_2 = "n1-standard-2"
    N1_STANDARD_4 = "n1-standard-4"
    N2_STANDARD_2 = "n2-standard-2"
    N2_STANDARD_4 = "n2-standard-4"


class GCPStorageClass(str, Enum):
    """GCS storage classes"""
    STANDARD = "STANDARD"
    NEARLINE = "NEARLINE"
    COLDLINE = "COLDLINE"
    ARCHIVE = "ARCHIVE"


# =============================================================================
# Base GCP Tool
# =============================================================================

class BaseGCPTool(BaseTool):
    """Base class for all GCP tools"""

    def __init__(
        self,
        metadata: ToolMetadata,
        project_id: Optional[str] = None,
        use_approval: bool = False,
        approval_manager: Optional[ApprovalManager] = None
    ):
        """
        Initialize GCP tool

        Args:
            metadata: Tool metadata
            project_id: GCP project ID (optional, uses gcloud config default if not provided)
            use_approval: Whether to require approval for dangerous operations
            approval_manager: Custom approval manager (for HITL)
        """
        super().__init__(metadata)
        self.project_id = project_id

        # Choose shell executor based on approval requirement
        if use_approval:
            self.shell = ApprovalShellExecutorTool(
                approval_manager=approval_manager or ApprovalManager(mode=ApprovalMode.INTERACTIVE)
            )
        else:
            self.shell = SafeShellExecutorTool()

    def _validate_config(self):
        """Validate gcloud CLI is installed"""
        result = self.shell.execute(command="gcloud --version", timeout=5)
        data = json.loads(result["result"])

        if not data["success"]:
            raise RuntimeError(
                "gcloud CLI not found. Install from: https://cloud.google.com/sdk/docs/install"
            )

    def _build_gcloud_command(self, command: str) -> str:
        """Build gcloud command with project flag"""
        if self.project_id:
            return f"gcloud {command} --project={self.project_id}"
        return f"gcloud {command}"

    def _execute_gcloud(
        self,
        command: str,
        timeout: int = 30,
        parse_json: bool = False
    ) -> Dict[str, Any]:
        """
        Execute gcloud command

        Args:
            command: gcloud command (without 'gcloud' prefix)
            timeout: Command timeout in seconds
            parse_json: Whether to parse output as JSON

        Returns:
            Shell execution result
        """
        full_command = self._build_gcloud_command(command)
        result = self.shell.execute(command=full_command, timeout=timeout)
        data = json.loads(result["result"])

        if parse_json and data["success"]:
            try:
                data["parsed_output"] = json.loads(data["stdout"])
            except json.JSONDecodeError:
                logger.warning("Failed to parse gcloud output as JSON")
                data["parsed_output"] = None

        return data


# =============================================================================
# Cloud Storage Tools
# =============================================================================

class GCPStorageTool(BaseGCPTool):
    """
    GCP Cloud Storage (GCS) operations

    Supports:
    - List buckets
    - Create/delete buckets
    - Upload/download files
    - List objects in bucket
    - Copy/move objects
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        use_approval: bool = False,
        approval_manager: Optional[ApprovalManager] = None
    ):
        metadata = ToolMetadata(
            name="gcp_storage",
            description="Manage GCP Cloud Storage buckets and objects",
            category="cloud",
            version="1.0.0",
            requires_auth=True
        )
        super().__init__(metadata, project_id, use_approval, approval_manager)

    def _execute(
        self,
        operation: str,
        bucket_name: Optional[str] = None,
        object_path: Optional[str] = None,
        local_path: Optional[str] = None,
        storage_class: str = "STANDARD",
        region: str = "us-central1"
    ) -> str:
        """
        Execute Cloud Storage operation

        Args:
            operation: Operation type (list_buckets, create_bucket, delete_bucket, upload, download, list_objects)
            bucket_name: Bucket name (required for most operations)
            object_path: Object path in bucket (e.g., 'folder/file.txt')
            local_path: Local file path for upload/download
            storage_class: Storage class for new buckets
            region: Region for new buckets

        Returns:
            Operation result as JSON string
        """

        # List buckets
        if operation == "list_buckets":
            result = self._execute_gcloud("storage buckets list --format=json", parse_json=True)
            if result["success"]:
                buckets = result.get("parsed_output", [])
                return json.dumps({
                    "success": True,
                    "bucket_count": len(buckets),
                    "buckets": [b.get("name") for b in buckets] if buckets else []
                }, indent=2)
            else:
                return json.dumps({"success": False, "error": result.get("error", result.get("stderr"))})

        # Create bucket
        elif operation == "create_bucket":
            if not bucket_name:
                return json.dumps({"success": False, "error": "bucket_name required"})

            cmd = f"storage buckets create gs://{bucket_name} --location={region} --storage-class={storage_class}"
            result = self._execute_gcloud(cmd, timeout=60)

            return json.dumps({
                "success": result["success"],
                "bucket": bucket_name,
                "region": region,
                "storage_class": storage_class,
                "message": f"Bucket gs://{bucket_name} created" if result["success"] else result.get("error", result.get("stderr"))
            }, indent=2)

        # Delete bucket
        elif operation == "delete_bucket":
            if not bucket_name:
                return json.dumps({"success": False, "error": "bucket_name required"})

            # This is a dangerous operation, will trigger approval if enabled
            result = self._execute_gcloud(f"storage buckets delete gs://{bucket_name} --quiet", timeout=60)

            return json.dumps({
                "success": result["success"],
                "bucket": bucket_name,
                "message": f"Bucket gs://{bucket_name} deleted" if result["success"] else result.get("error", result.get("stderr"))
            }, indent=2)

        # List objects in bucket
        elif operation == "list_objects":
            if not bucket_name:
                return json.dumps({"success": False, "error": "bucket_name required"})

            gs_path = f"gs://{bucket_name}/" if not object_path else f"gs://{bucket_name}/{object_path}"
            result = self._execute_gcloud(f"storage ls {gs_path} --format=json", parse_json=True)

            if result["success"]:
                objects = result.get("parsed_output", [])
                return json.dumps({
                    "success": True,
                    "bucket": bucket_name,
                    "object_count": len(objects),
                    "objects": objects
                }, indent=2)
            else:
                return json.dumps({"success": False, "error": result.get("error", result.get("stderr"))})

        # Upload file
        elif operation == "upload":
            if not bucket_name or not local_path:
                return json.dumps({"success": False, "error": "bucket_name and local_path required"})

            gs_path = f"gs://{bucket_name}/" if not object_path else f"gs://{bucket_name}/{object_path}"
            result = self._execute_gcloud(f"storage cp {local_path} {gs_path}", timeout=300)

            return json.dumps({
                "success": result["success"],
                "local_path": local_path,
                "gs_path": gs_path,
                "message": f"Uploaded {local_path} to {gs_path}" if result["success"] else result.get("error", result.get("stderr"))
            }, indent=2)

        # Download file
        elif operation == "download":
            if not bucket_name or not local_path:
                return json.dumps({"success": False, "error": "bucket_name and local_path required"})

            gs_path = f"gs://{bucket_name}/" if not object_path else f"gs://{bucket_name}/{object_path}"
            result = self._execute_gcloud(f"storage cp {gs_path} {local_path}", timeout=300)

            return json.dumps({
                "success": result["success"],
                "gs_path": gs_path,
                "local_path": local_path,
                "message": f"Downloaded {gs_path} to {local_path}" if result["success"] else result.get("error", result.get("stderr"))
            }, indent=2)

        else:
            return json.dumps({
                "success": False,
                "error": f"Unknown operation: {operation}. Valid operations: list_buckets, create_bucket, delete_bucket, list_objects, upload, download"
            })


# =============================================================================
# BigQuery Tools
# =============================================================================

class GCPBigQueryTool(BaseGCPTool):
    """
    GCP BigQuery operations

    Supports:
    - Execute queries
    - List datasets
    - List tables
    - Create datasets
    - Export query results
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        use_approval: bool = False,
        approval_manager: Optional[ApprovalManager] = None
    ):
        metadata = ToolMetadata(
            name="gcp_bigquery",
            description="Execute BigQuery queries and manage datasets",
            category="cloud",
            version="1.0.0",
            requires_auth=True
        )
        super().__init__(metadata, project_id, use_approval, approval_manager)

    def _execute(
        self,
        operation: str,
        query: Optional[str] = None,
        dataset_id: Optional[str] = None,
        table_id: Optional[str] = None,
        location: str = "US",
        max_results: int = 100
    ) -> str:
        """
        Execute BigQuery operation

        Args:
            operation: Operation type (query, list_datasets, list_tables, create_dataset)
            query: SQL query to execute
            dataset_id: Dataset ID
            table_id: Table ID
            location: Dataset location (default: US)
            max_results: Maximum results to return for queries

        Returns:
            Operation result as JSON string
        """

        # Execute query
        if operation == "query":
            if not query:
                return json.dumps({"success": False, "error": "query required"})

            # Escape quotes in query
            query_escaped = query.replace('"', '\\"')
            cmd = f'bq query --use_legacy_sql=false --format=json --max_rows={max_results} "{query_escaped}"'

            result = self._execute_gcloud(cmd, timeout=300, parse_json=True)

            if result["success"]:
                rows = result.get("parsed_output", [])
                return json.dumps({
                    "success": True,
                    "row_count": len(rows),
                    "rows": rows
                }, indent=2)
            else:
                return json.dumps({"success": False, "error": result.get("error", result.get("stderr"))})

        # List datasets
        elif operation == "list_datasets":
            result = self._execute_gcloud("bq ls --format=json", parse_json=True)

            if result["success"]:
                datasets = result.get("parsed_output", [])
                return json.dumps({
                    "success": True,
                    "dataset_count": len(datasets),
                    "datasets": [d.get("datasetReference", {}).get("datasetId") for d in datasets] if datasets else []
                }, indent=2)
            else:
                return json.dumps({"success": False, "error": result.get("error", result.get("stderr"))})

        # List tables in dataset
        elif operation == "list_tables":
            if not dataset_id:
                return json.dumps({"success": False, "error": "dataset_id required"})

            result = self._execute_gcloud(f"bq ls --format=json {dataset_id}", parse_json=True)

            if result["success"]:
                tables = result.get("parsed_output", [])
                return json.dumps({
                    "success": True,
                    "dataset": dataset_id,
                    "table_count": len(tables),
                    "tables": [t.get("tableReference", {}).get("tableId") for t in tables] if tables else []
                }, indent=2)
            else:
                return json.dumps({"success": False, "error": result.get("error", result.get("stderr"))})

        # Create dataset
        elif operation == "create_dataset":
            if not dataset_id:
                return json.dumps({"success": False, "error": "dataset_id required"})

            result = self._execute_gcloud(f"bq mk --dataset --location={location} {dataset_id}", timeout=60)

            return json.dumps({
                "success": result["success"],
                "dataset": dataset_id,
                "location": location,
                "message": f"Dataset {dataset_id} created" if result["success"] else result.get("error", result.get("stderr"))
            }, indent=2)

        # Delete dataset
        elif operation == "delete_dataset":
            if not dataset_id:
                return json.dumps({"success": False, "error": "dataset_id required"})

            # Dangerous operation, will trigger approval if enabled
            result = self._execute_gcloud(f"bq rm -r -f -d {dataset_id}", timeout=60)

            return json.dumps({
                "success": result["success"],
                "dataset": dataset_id,
                "message": f"Dataset {dataset_id} deleted" if result["success"] else result.get("error", result.get("stderr"))
            }, indent=2)

        else:
            return json.dumps({
                "success": False,
                "error": f"Unknown operation: {operation}. Valid operations: query, list_datasets, list_tables, create_dataset, delete_dataset"
            })


# =============================================================================
# Compute Engine Tools
# =============================================================================

class GCPComputeTool(BaseGCPTool):
    """
    GCP Compute Engine operations

    Supports:
    - List VM instances
    - Start/stop instances
    - Create instances
    - Delete instances
    - Get instance details
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        use_approval: bool = False,
        approval_manager: Optional[ApprovalManager] = None
    ):
        metadata = ToolMetadata(
            name="gcp_compute",
            description="Manage GCP Compute Engine VM instances",
            category="cloud",
            version="1.0.0",
            requires_auth=True
        )
        super().__init__(metadata, project_id, use_approval, approval_manager)

    def _execute(
        self,
        operation: str,
        instance_name: Optional[str] = None,
        zone: str = "us-central1-a",
        machine_type: str = "e2-medium",
        image_family: str = "debian-11",
        image_project: str = "debian-cloud"
    ) -> str:
        """
        Execute Compute Engine operation

        Args:
            operation: Operation type (list, start, stop, create, delete, describe)
            instance_name: Instance name
            zone: GCP zone (e.g., us-central1-a)
            machine_type: Machine type for new instances
            image_family: Image family for new instances
            image_project: Image project for new instances

        Returns:
            Operation result as JSON string
        """

        # List instances
        if operation == "list":
            result = self._execute_gcloud(f"compute instances list --format=json", parse_json=True)

            if result["success"]:
                instances = result.get("parsed_output", [])
                return json.dumps({
                    "success": True,
                    "instance_count": len(instances),
                    "instances": [{
                        "name": inst.get("name"),
                        "zone": inst.get("zone", "").split("/")[-1],
                        "machine_type": inst.get("machineType", "").split("/")[-1],
                        "status": inst.get("status")
                    } for inst in instances] if instances else []
                }, indent=2)
            else:
                return json.dumps({"success": False, "error": result.get("error", result.get("stderr"))})

        # Start instance
        elif operation == "start":
            if not instance_name:
                return json.dumps({"success": False, "error": "instance_name required"})

            result = self._execute_gcloud(f"compute instances start {instance_name} --zone={zone}", timeout=120)

            return json.dumps({
                "success": result["success"],
                "instance": instance_name,
                "zone": zone,
                "message": f"Instance {instance_name} started" if result["success"] else result.get("error", result.get("stderr"))
            }, indent=2)

        # Stop instance
        elif operation == "stop":
            if not instance_name:
                return json.dumps({"success": False, "error": "instance_name required"})

            result = self._execute_gcloud(f"compute instances stop {instance_name} --zone={zone}", timeout=120)

            return json.dumps({
                "success": result["success"],
                "instance": instance_name,
                "zone": zone,
                "message": f"Instance {instance_name} stopped" if result["success"] else result.get("error", result.get("stderr"))
            }, indent=2)

        # Create instance
        elif operation == "create":
            if not instance_name:
                return json.dumps({"success": False, "error": "instance_name required"})

            cmd = (
                f"compute instances create {instance_name} "
                f"--zone={zone} "
                f"--machine-type={machine_type} "
                f"--image-family={image_family} "
                f"--image-project={image_project}"
            )
            result = self._execute_gcloud(cmd, timeout=300)

            return json.dumps({
                "success": result["success"],
                "instance": instance_name,
                "zone": zone,
                "machine_type": machine_type,
                "message": f"Instance {instance_name} created" if result["success"] else result.get("error", result.get("stderr"))
            }, indent=2)

        # Delete instance
        elif operation == "delete":
            if not instance_name:
                return json.dumps({"success": False, "error": "instance_name required"})

            # Dangerous operation, will trigger approval if enabled
            result = self._execute_gcloud(f"compute instances delete {instance_name} --zone={zone} --quiet", timeout=120)

            return json.dumps({
                "success": result["success"],
                "instance": instance_name,
                "zone": zone,
                "message": f"Instance {instance_name} deleted" if result["success"] else result.get("error", result.get("stderr"))
            }, indent=2)

        # Describe instance
        elif operation == "describe":
            if not instance_name:
                return json.dumps({"success": False, "error": "instance_name required"})

            result = self._execute_gcloud(f"compute instances describe {instance_name} --zone={zone} --format=json", parse_json=True)

            if result["success"]:
                instance_details = result.get("parsed_output", {})
                return json.dumps({
                    "success": True,
                    "instance": instance_name,
                    "details": instance_details
                }, indent=2)
            else:
                return json.dumps({"success": False, "error": result.get("error", result.get("stderr"))})

        else:
            return json.dumps({
                "success": False,
                "error": f"Unknown operation: {operation}. Valid operations: list, start, stop, create, delete, describe"
            })


# =============================================================================
# IAM Tools
# =============================================================================

class GCPIAMTool(BaseGCPTool):
    """
    GCP IAM (Identity and Access Management) operations

    Supports:
    - List service accounts
    - Create service accounts
    - List IAM policies
    - Grant/revoke roles
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        use_approval: bool = True,  # IAM operations should require approval by default
        approval_manager: Optional[ApprovalManager] = None
    ):
        metadata = ToolMetadata(
            name="gcp_iam",
            description="Manage GCP IAM policies and service accounts",
            category="cloud",
            version="1.0.0",
            requires_auth=True
        )
        super().__init__(metadata, project_id, use_approval, approval_manager)

    def _execute(
        self,
        operation: str,
        service_account_name: Optional[str] = None,
        display_name: Optional[str] = None,
        member: Optional[str] = None,
        role: Optional[str] = None
    ) -> str:
        """
        Execute IAM operation

        Args:
            operation: Operation type (list_service_accounts, create_service_account, list_policies, add_binding, remove_binding)
            service_account_name: Service account name
            display_name: Display name for new service accounts
            member: Member to grant/revoke roles (e.g., user:email@example.com, serviceAccount:sa@project.iam.gserviceaccount.com)
            role: IAM role to grant/revoke (e.g., roles/viewer, roles/editor)

        Returns:
            Operation result as JSON string
        """

        # List service accounts
        if operation == "list_service_accounts":
            result = self._execute_gcloud("iam service-accounts list --format=json", parse_json=True)

            if result["success"]:
                accounts = result.get("parsed_output", [])
                return json.dumps({
                    "success": True,
                    "account_count": len(accounts),
                    "accounts": [{
                        "email": acc.get("email"),
                        "displayName": acc.get("displayName"),
                        "disabled": acc.get("disabled", False)
                    } for acc in accounts] if accounts else []
                }, indent=2)
            else:
                return json.dumps({"success": False, "error": result.get("error", result.get("stderr"))})

        # Create service account
        elif operation == "create_service_account":
            if not service_account_name:
                return json.dumps({"success": False, "error": "service_account_name required"})

            cmd = f"iam service-accounts create {service_account_name}"
            if display_name:
                cmd += f" --display-name='{display_name}'"

            result = self._execute_gcloud(cmd, timeout=60)

            return json.dumps({
                "success": result["success"],
                "service_account": service_account_name,
                "message": f"Service account {service_account_name} created" if result["success"] else result.get("error", result.get("stderr"))
            }, indent=2)

        # List IAM policy bindings
        elif operation == "list_policies":
            result = self._execute_gcloud("projects get-iam-policy $(gcloud config get-value project) --format=json", parse_json=True)

            if result["success"]:
                policy = result.get("parsed_output", {})
                bindings = policy.get("bindings", [])
                return json.dumps({
                    "success": True,
                    "binding_count": len(bindings),
                    "bindings": bindings
                }, indent=2)
            else:
                return json.dumps({"success": False, "error": result.get("error", result.get("stderr"))})

        # Add IAM policy binding
        elif operation == "add_binding":
            if not member or not role:
                return json.dumps({"success": False, "error": "member and role required"})

            # This is a dangerous operation, will trigger approval
            result = self._execute_gcloud(
                f"projects add-iam-policy-binding $(gcloud config get-value project) --member={member} --role={role}",
                timeout=60
            )

            return json.dumps({
                "success": result["success"],
                "member": member,
                "role": role,
                "message": f"Role {role} granted to {member}" if result["success"] else result.get("error", result.get("stderr"))
            }, indent=2)

        # Remove IAM policy binding
        elif operation == "remove_binding":
            if not member or not role:
                return json.dumps({"success": False, "error": "member and role required"})

            # This is a dangerous operation, will trigger approval
            result = self._execute_gcloud(
                f"projects remove-iam-policy-binding $(gcloud config get-value project) --member={member} --role={role}",
                timeout=60
            )

            return json.dumps({
                "success": result["success"],
                "member": member,
                "role": role,
                "message": f"Role {role} revoked from {member}" if result["success"] else result.get("error", result.get("stderr"))
            }, indent=2)

        else:
            return json.dumps({
                "success": False,
                "error": f"Unknown operation: {operation}. Valid operations: list_service_accounts, create_service_account, list_policies, add_binding, remove_binding"
            })
