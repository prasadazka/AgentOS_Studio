"""Infrastructure Tools - Terraform Generator, VPC Config, Cloud SQL"""

import subprocess
import shutil
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Type-Safe Models
# =============================================================================

class TerraformResult(BaseModel):
    """Result of Terraform operations"""
    success: bool
    files_generated: List[str] = Field(default_factory=list)
    output_dir: Optional[str] = None
    resources: List[str] = Field(default_factory=list)
    message: str = ""
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class VPCResult(BaseModel):
    """Result of VPC configuration"""
    success: bool
    vpc_name: Optional[str] = None
    subnet_name: Optional[str] = None
    region: Optional[str] = None
    cidr_range: Optional[str] = None
    firewall_rules: List[str] = Field(default_factory=list)
    message: str = ""
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class CloudSQLResult(BaseModel):
    """Result of Cloud SQL operations"""
    success: bool
    instance_name: Optional[str] = None
    database_name: Optional[str] = None
    connection_name: Optional[str] = None
    public_ip: Optional[str] = None
    private_ip: Optional[str] = None
    tier: Optional[str] = None
    message: str = ""
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Terraform Generator Tool
# =============================================================================

class TerraformGeneratorTool(BaseTool):
    """Generate Terraform configuration files for GCP infrastructure

    Supports:
    - Cloud Run services
    - VPC networks
    - Cloud SQL instances
    - Secret Manager
    - Load balancers
    """

    # Terraform templates
    MAIN_TF_TEMPLATE = '''terraform {{
  required_version = ">= 1.0"
  required_providers {{
    google = {{
      source  = "hashicorp/google"
      version = "~> 5.0"
    }}
  }}
  backend "gcs" {{
    bucket = "{state_bucket}"
    prefix = "terraform/state"
  }}
}}

provider "google" {{
  project = var.project_id
  region  = var.region
}}

provider "google-beta" {{
  project = var.project_id
  region  = var.region
}}
'''

    VARIABLES_TF_TEMPLATE = '''variable "project_id" {{
  description = "GCP Project ID"
  type        = string
}}

variable "region" {{
  description = "GCP Region"
  type        = string
  default     = "{region}"
}}

variable "environment" {{
  description = "Environment (dev, staging, prod)"
  type        = string
  default     = "prod"
}}

variable "service_name" {{
  description = "Name of the Cloud Run service"
  type        = string
  default     = "{service_name}"
}}
'''

    CLOUD_RUN_TF_TEMPLATE = '''# Cloud Run Service
resource "google_cloud_run_v2_service" "{resource_name}" {{
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {{
    containers {{
      image = var.container_image

      resources {{
        limits = {{
          cpu    = "{cpu_limit}"
          memory = "{memory_limit}"
        }}
        cpu_idle = {cpu_idle}
        startup_cpu_boost = true
      }}

      # Environment variables from Secret Manager
      dynamic "env" {{
        for_each = var.env_secrets
        content {{
          name = env.value.name
          value_source {{
            secret_key_ref {{
              secret  = env.value.secret
              version = "latest"
            }}
          }}
        }}
      }}
    }}

    scaling {{
      min_instance_count = {min_instances}
      max_instance_count = {max_instances}
    }}

    service_account = google_service_account.cloud_run_sa.email
  }}

  traffic {{
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }}
}}

# Service Account for Cloud Run
resource "google_service_account" "cloud_run_sa" {{
  account_id   = "${{var.service_name}}-sa"
  display_name = "Service Account for ${{var.service_name}}"
}}

# IAM binding for public access (if needed)
resource "google_cloud_run_v2_service_iam_member" "public_access" {{
  count    = var.allow_unauthenticated ? 1 : 0
  location = google_cloud_run_v2_service.{resource_name}.location
  name     = google_cloud_run_v2_service.{resource_name}.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}}

output "service_url" {{
  value = google_cloud_run_v2_service.{resource_name}.uri
}}
'''

    VPC_TF_TEMPLATE = '''# VPC Network
resource "google_compute_network" "{vpc_name}" {{
  name                    = "{vpc_name}"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
}}

# Subnet
resource "google_compute_subnetwork" "{subnet_name}" {{
  name          = "{subnet_name}"
  ip_cidr_range = "{cidr_range}"
  region        = var.region
  network       = google_compute_network.{vpc_name}.id

  private_ip_google_access = true

  log_config {{
    aggregation_interval = "INTERVAL_10_MIN"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }}
}}

# VPC Connector for Cloud Run
resource "google_vpc_access_connector" "{vpc_name}_connector" {{
  name          = "{vpc_name}-connector"
  region        = var.region
  network       = google_compute_network.{vpc_name}.id
  ip_cidr_range = "10.8.0.0/28"
  min_instances = 2
  max_instances = 10
}}

# Firewall rules
resource "google_compute_firewall" "allow_internal" {{
  name    = "{vpc_name}-allow-internal"
  network = google_compute_network.{vpc_name}.name

  allow {{
    protocol = "tcp"
    ports    = ["0-65535"]
  }}

  allow {{
    protocol = "udp"
    ports    = ["0-65535"]
  }}

  allow {{
    protocol = "icmp"
  }}

  source_ranges = ["{cidr_range}"]
}}

resource "google_compute_firewall" "allow_health_check" {{
  name    = "{vpc_name}-allow-health-check"
  network = google_compute_network.{vpc_name}.name

  allow {{
    protocol = "tcp"
    ports    = ["80", "443", "8080"]
  }}

  source_ranges = ["130.211.0.0/22", "35.191.0.0/16"]
  target_tags   = ["allow-health-check"]
}}
'''

    CLOUD_SQL_TF_TEMPLATE = '''# Cloud SQL Instance
resource "google_sql_database_instance" "{instance_name}" {{
  name             = "{instance_name}"
  database_version = "{database_version}"
  region           = var.region

  settings {{
    tier              = "{tier}"
    availability_type = "{availability_type}"
    disk_size         = {disk_size}
    disk_type         = "PD_SSD"

    backup_configuration {{
      enabled                        = true
      binary_log_enabled             = {binary_log_enabled}
      start_time                     = "02:00"
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7

      backup_retention_settings {{
        retained_backups = 7
      }}
    }}

    ip_configuration {{
      ipv4_enabled    = {public_ip_enabled}
      private_network = {private_network}
      require_ssl     = true
    }}

    maintenance_window {{
      day          = 7
      hour         = 3
      update_track = "stable"
    }}

    insights_config {{
      query_insights_enabled  = true
      query_string_length     = 1024
      record_application_tags = true
      record_client_address   = true
    }}
  }}

  deletion_protection = {deletion_protection}
}}

# Database
resource "google_sql_database" "{database_name}" {{
  name     = "{database_name}"
  instance = google_sql_database_instance.{instance_name}.name
}}

# Random password for database user
resource "random_password" "db_password" {{
  length  = 32
  special = true
}}

# Database User
resource "google_sql_user" "{user_name}" {{
  name     = "{user_name}"
  instance = google_sql_database_instance.{instance_name}.name
  password = random_password.db_password.result
}}

# Store password in Secret Manager
resource "google_secret_manager_secret" "db_password" {{
  secret_id = "{instance_name}-password"
  replication {{
    auto {{}}
  }}
}}

resource "google_secret_manager_secret_version" "db_password" {{
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.db_password.result
}}

output "connection_name" {{
  value = google_sql_database_instance.{instance_name}.connection_name
}}
'''

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="terraform_generator",
                description="Generate Terraform configuration files for GCP infrastructure",
                category="infrastructure",
                version="1.0.0",
            )
        )

    def _execute(
        self,
        output_dir: str = "./terraform",
        project_id: str = "my-project",
        region: str = "us-central1",
        service_name: str = "my-service",
        state_bucket: Optional[str] = None,
        include_vpc: bool = True,
        include_cloud_sql: bool = False,
        include_secrets: bool = True,
        min_instances: int = 0,
        max_instances: int = 100,
        cpu_limit: str = "1000m",
        memory_limit: str = "512Mi",
        database_version: str = "POSTGRES_15",
        database_tier: str = "db-f1-micro",
    ) -> str:
        """Generate Terraform configuration files"""

        try:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            files_generated = []
            resources = []

            # Generate main.tf
            state_bucket = state_bucket or f"{project_id}-terraform-state"
            main_tf = self.MAIN_TF_TEMPLATE.format(state_bucket=state_bucket)
            (output_path / "main.tf").write_text(main_tf)
            files_generated.append("main.tf")

            # Generate variables.tf
            variables_tf = self.VARIABLES_TF_TEMPLATE.format(
                region=region,
                service_name=service_name,
            )
            (output_path / "variables.tf").write_text(variables_tf)
            files_generated.append("variables.tf")

            # Generate cloud_run.tf
            resource_name = service_name.replace("-", "_")
            cloud_run_tf = self.CLOUD_RUN_TF_TEMPLATE.format(
                resource_name=resource_name,
                cpu_limit=cpu_limit,
                memory_limit=memory_limit,
                cpu_idle="true" if min_instances == 0 else "false",
                min_instances=min_instances,
                max_instances=max_instances,
            )
            (output_path / "cloud_run.tf").write_text(cloud_run_tf)
            files_generated.append("cloud_run.tf")
            resources.append("google_cloud_run_v2_service")

            # Generate vpc.tf if requested
            if include_vpc:
                vpc_name = f"{service_name}-vpc"
                subnet_name = f"{service_name}-subnet"
                vpc_tf = self.VPC_TF_TEMPLATE.format(
                    vpc_name=vpc_name.replace("-", "_"),
                    subnet_name=subnet_name.replace("-", "_"),
                    cidr_range="10.0.0.0/20",
                )
                (output_path / "vpc.tf").write_text(vpc_tf)
                files_generated.append("vpc.tf")
                resources.extend([
                    "google_compute_network",
                    "google_compute_subnetwork",
                    "google_vpc_access_connector",
                ])

            # Generate cloud_sql.tf if requested
            if include_cloud_sql:
                instance_name = f"{service_name}-db".replace("-", "_")
                cloud_sql_tf = self.CLOUD_SQL_TF_TEMPLATE.format(
                    instance_name=instance_name,
                    database_name=f"{service_name}_db",
                    user_name="app_user",
                    database_version=database_version,
                    tier=database_tier,
                    availability_type="ZONAL",
                    disk_size=10,
                    binary_log_enabled="true" if "MYSQL" in database_version else "false",
                    public_ip_enabled="false",
                    private_network="google_compute_network.{}_vpc.id".format(service_name.replace("-", "_")) if include_vpc else "null",
                    deletion_protection="true",
                )
                (output_path / "cloud_sql.tf").write_text(cloud_sql_tf)
                files_generated.append("cloud_sql.tf")
                resources.extend([
                    "google_sql_database_instance",
                    "google_sql_database",
                ])

            # Generate terraform.tfvars template
            tfvars_content = f'''project_id = "{project_id}"
region     = "{region}"
environment = "prod"
service_name = "{service_name}"

# Container image (update with your image)
container_image = "gcr.io/{project_id}/{service_name}:latest"

# Set to true for public access
allow_unauthenticated = false

# Environment secrets (from Secret Manager)
env_secrets = [
  # {{ name = "DATABASE_URL", secret = "database-url" }},
]
'''
            (output_path / "terraform.tfvars.example").write_text(tfvars_content)
            files_generated.append("terraform.tfvars.example")

            # Generate .gitignore
            gitignore_content = '''*.tfstate
*.tfstate.*
.terraform/
.terraform.lock.hcl
*.tfvars
!*.tfvars.example
'''
            (output_path / ".gitignore").write_text(gitignore_content)
            files_generated.append(".gitignore")

            return TerraformResult(
                success=True,
                files_generated=files_generated,
                output_dir=str(output_path),
                resources=resources,
                message=f"Generated {len(files_generated)} Terraform files in {output_dir}"
            ).to_json()

        except Exception as e:
            return TerraformResult(
                success=False,
                error=str(e)
            ).to_json()


# =============================================================================
# VPC Configuration Tool
# =============================================================================

class VPCConfigTool(BaseTool):
    """Configure VPC networks and firewall rules

    Features:
    - Create VPC with subnets
    - Configure firewall rules
    - Set up VPC connectors for Cloud Run
    - Private Google Access
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="vpc_config",
                description="Configure VPC networks and firewall rules",
                category="infrastructure",
                version="1.0.0",
                requires_auth=True,
            )
        )
        self._gcloud_path = shutil.which("gcloud")

    def _execute(
        self,
        vpc_name: str,
        region: str = "us-central1",
        project_id: Optional[str] = None,
        subnet_cidr: str = "10.0.0.0/20",
        create_connector: bool = True,
        connector_cidr: str = "10.8.0.0/28",
        firewall_rules: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Configure VPC network"""

        if not self._gcloud_path:
            return VPCResult(
                success=False,
                error="gcloud CLI not found"
            ).to_json()

        try:
            created_rules = []

            # Create VPC
            cmd = [
                self._gcloud_path, "compute", "networks", "create", vpc_name,
                "--subnet-mode=custom",
            ]
            if project_id:
                cmd.append(f"--project={project_id}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0 and "already exists" not in result.stderr:
                return VPCResult(success=False, error=f"VPC creation failed: {result.stderr}").to_json()

            # Create subnet
            subnet_name = f"{vpc_name}-subnet"
            cmd = [
                self._gcloud_path, "compute", "networks", "subnets", "create", subnet_name,
                f"--network={vpc_name}",
                f"--region={region}",
                f"--range={subnet_cidr}",
                "--enable-private-ip-google-access",
            ]
            if project_id:
                cmd.append(f"--project={project_id}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0 and "already exists" not in result.stderr:
                return VPCResult(success=False, error=f"Subnet creation failed: {result.stderr}").to_json()

            # Create VPC connector for Cloud Run
            if create_connector:
                connector_name = f"{vpc_name}-connector"
                cmd = [
                    self._gcloud_path, "compute", "networks", "vpc-access", "connectors", "create", connector_name,
                    f"--network={vpc_name}",
                    f"--region={region}",
                    f"--range={connector_cidr}",
                    "--min-instances=2",
                    "--max-instances=10",
                ]
                if project_id:
                    cmd.append(f"--project={project_id}")

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if result.returncode == 0:
                    created_rules.append(f"VPC Connector: {connector_name}")

            # Create default firewall rules
            default_rules = [
                {
                    "name": f"{vpc_name}-allow-internal",
                    "direction": "INGRESS",
                    "source_ranges": [subnet_cidr],
                    "allow": [{"protocol": "tcp"}, {"protocol": "udp"}, {"protocol": "icmp"}],
                },
                {
                    "name": f"{vpc_name}-allow-health-check",
                    "direction": "INGRESS",
                    "source_ranges": ["130.211.0.0/22", "35.191.0.0/16"],
                    "allow": [{"protocol": "tcp", "ports": ["80", "443", "8080"]}],
                },
            ]

            rules_to_create = firewall_rules or default_rules

            for rule in rules_to_create:
                rule_name = rule.get("name", f"{vpc_name}-rule")
                cmd = [
                    self._gcloud_path, "compute", "firewall-rules", "create", rule_name,
                    f"--network={vpc_name}",
                    f"--direction={rule.get('direction', 'INGRESS')}",
                ]

                if rule.get("source_ranges"):
                    cmd.append(f"--source-ranges={','.join(rule['source_ranges'])}")

                for allow in rule.get("allow", []):
                    proto = allow.get("protocol", "tcp")
                    if allow.get("ports"):
                        cmd.append(f"--allow={proto}:{','.join(allow['ports'])}")
                    else:
                        cmd.append(f"--allow={proto}")

                if project_id:
                    cmd.append(f"--project={project_id}")

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    created_rules.append(rule_name)

            return VPCResult(
                success=True,
                vpc_name=vpc_name,
                subnet_name=subnet_name,
                region=region,
                cidr_range=subnet_cidr,
                firewall_rules=created_rules,
                message=f"VPC '{vpc_name}' configured with {len(created_rules)} rules"
            ).to_json()

        except Exception as e:
            return VPCResult(
                success=False,
                error=str(e)
            ).to_json()


# =============================================================================
# Cloud SQL Provisioning Tool
# =============================================================================

class CloudSQLProvisioningTool(BaseTool):
    """Provision Cloud SQL instances

    Features:
    - PostgreSQL and MySQL support
    - High availability configuration
    - Automated backups
    - Private IP configuration
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="cloud_sql_provisioning",
                description="Provision Cloud SQL database instances",
                category="infrastructure",
                version="1.0.0",
                requires_auth=True,
            )
        )
        self._gcloud_path = shutil.which("gcloud")

    def _execute(
        self,
        instance_name: str,
        database_name: str,
        region: str = "us-central1",
        project_id: Optional[str] = None,
        database_version: str = "POSTGRES_15",  # or MYSQL_8_0
        tier: str = "db-f1-micro",  # or db-custom-2-4096
        disk_size_gb: int = 10,
        high_availability: bool = False,
        enable_backups: bool = True,
        private_network: Optional[str] = None,
        authorized_networks: Optional[List[str]] = None,
    ) -> str:
        """Provision Cloud SQL instance"""

        if not self._gcloud_path:
            return CloudSQLResult(
                success=False,
                error="gcloud CLI not found"
            ).to_json()

        try:
            # Create instance
            cmd = [
                self._gcloud_path, "sql", "instances", "create", instance_name,
                f"--database-version={database_version}",
                f"--tier={tier}",
                f"--region={region}",
                f"--storage-size={disk_size_gb}GB",
                "--storage-type=SSD",
                "--storage-auto-increase",
            ]

            if project_id:
                cmd.append(f"--project={project_id}")

            if high_availability:
                cmd.append("--availability-type=REGIONAL")
            else:
                cmd.append("--availability-type=ZONAL")

            if enable_backups:
                cmd.extend([
                    "--backup",
                    "--backup-start-time=02:00",
                ])

            if private_network:
                cmd.extend([
                    f"--network={private_network}",
                    "--no-assign-ip",
                ])
            else:
                cmd.append("--assign-ip")

            if authorized_networks:
                for i, network in enumerate(authorized_networks):
                    cmd.append(f"--authorized-networks={network}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

            if result.returncode != 0:
                return CloudSQLResult(
                    success=False,
                    instance_name=instance_name,
                    error=result.stderr
                ).to_json()

            # Create database
            cmd = [
                self._gcloud_path, "sql", "databases", "create", database_name,
                f"--instance={instance_name}",
            ]
            if project_id:
                cmd.append(f"--project={project_id}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            # Get instance details
            cmd = [
                self._gcloud_path, "sql", "instances", "describe", instance_name,
                "--format=json",
            ]
            if project_id:
                cmd.append(f"--project={project_id}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            connection_name = None
            public_ip = None
            private_ip = None

            if result.returncode == 0:
                try:
                    data = json.loads(result.stdout)
                    connection_name = data.get("connectionName")
                    for ip_config in data.get("ipAddresses", []):
                        if ip_config.get("type") == "PRIMARY":
                            public_ip = ip_config.get("ipAddress")
                        elif ip_config.get("type") == "PRIVATE":
                            private_ip = ip_config.get("ipAddress")
                except json.JSONDecodeError:
                    pass

            return CloudSQLResult(
                success=True,
                instance_name=instance_name,
                database_name=database_name,
                connection_name=connection_name,
                public_ip=public_ip,
                private_ip=private_ip,
                tier=tier,
                message=f"Cloud SQL instance '{instance_name}' created successfully"
            ).to_json()

        except Exception as e:
            return CloudSQLResult(
                success=False,
                error=str(e)
            ).to_json()
