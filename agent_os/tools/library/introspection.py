"""
Deployment Introspection Tools for AgentOS

Tools for reading, understanding, and analyzing existing cloud deployments.
Enables the system to discover services, read configurations, compare revisions,
monitor health, and analyze resource usage.
"""

import json
import shutil
import subprocess
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from agent_os.tools.base import BaseTool, ToolMetadata


class CloudRunServiceDiscoveryTool(BaseTool):
    """
    Discover and list existing Cloud Run services.

    Returns detailed information about deployed services including:
    - Service name, region, URL
    - Current revision and traffic allocation
    - Last deployment time
    - Service status
    """

    def __init__(self):
        self._gcloud_path = shutil.which("gcloud")
        metadata = ToolMetadata(
            name="cloud_run_service_discovery",
            description="Discover and list existing Cloud Run services with their details",
            category="introspection",
            version="1.0.0",
            requires_auth=True,
        )
        super().__init__(metadata)

    def _validate_config(self):
        """Validate gcloud CLI is available"""
        if not self._gcloud_path:
            raise RuntimeError(
                "gcloud CLI not found. Install Google Cloud SDK: "
                "https://cloud.google.com/sdk/docs/install"
            )

    def _execute(
        self,
        project_id: str,
        region: Optional[str] = None,
        service_name: Optional[str] = None,
        include_revisions: bool = False,
    ) -> Dict[str, Any]:
        """
        Discover Cloud Run services.

        Args:
            project_id: GCP project ID
            region: Optional region filter (e.g., 'us-central1'). If None, lists all regions.
            service_name: Optional specific service to describe in detail
            include_revisions: If True, include revision history for each service

        Returns:
            Dictionary with discovered services and their details
        """
        try:
            if service_name and region:
                # Get detailed info for specific service
                return self._describe_service(project_id, region, service_name, include_revisions)
            else:
                # List all services
                return self._list_services(project_id, region, include_revisions)
        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "error": f"Failed to discover services: {e.stderr}",
            }

    def _list_services(
        self, project_id: str, region: Optional[str], include_revisions: bool
    ) -> Dict[str, Any]:
        """List all Cloud Run services"""
        cmd = [
            self._gcloud_path,
            "run",
            "services",
            "list",
            "--project", project_id,
            "--format", "json",
        ]

        if region:
            cmd.extend(["--region", region])

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        services = json.loads(result.stdout) if result.stdout else []

        # Parse and enrich service data
        parsed_services = []
        for svc in services:
            parsed = self._parse_service(svc)

            if include_revisions:
                # Get revision history
                svc_region = svc.get("metadata", {}).get("labels", {}).get("cloud.googleapis.com/location", "")
                svc_name = svc.get("metadata", {}).get("name", "")
                if svc_region and svc_name:
                    revisions = self._get_revisions(project_id, svc_region, svc_name)
                    parsed["revisions"] = revisions

            parsed_services.append(parsed)

        return {
            "success": True,
            "project_id": project_id,
            "region_filter": region or "all",
            "service_count": len(parsed_services),
            "services": parsed_services,
        }

    def _describe_service(
        self, project_id: str, region: str, service_name: str, include_revisions: bool
    ) -> Dict[str, Any]:
        """Get detailed info for a specific service"""
        cmd = [
            self._gcloud_path,
            "run",
            "services",
            "describe",
            service_name,
            "--project", project_id,
            "--region", region,
            "--format", "json",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        service = json.loads(result.stdout) if result.stdout else {}

        parsed = self._parse_service(service, detailed=True)

        if include_revisions:
            parsed["revisions"] = self._get_revisions(project_id, region, service_name)

        return {
            "success": True,
            "service": parsed,
        }

    def _parse_service(self, svc: Dict, detailed: bool = False) -> Dict[str, Any]:
        """Parse service data into a clean format"""
        metadata = svc.get("metadata", {})
        status = svc.get("status", {})
        spec = svc.get("spec", {})

        # Extract traffic allocation
        traffic = status.get("traffic", [])
        traffic_allocation = []
        for t in traffic:
            traffic_allocation.append({
                "revision": t.get("revisionName", "latest"),
                "percent": t.get("percent", 0),
                "tag": t.get("tag", ""),
            })

        parsed = {
            "name": metadata.get("name", ""),
            "region": metadata.get("labels", {}).get("cloud.googleapis.com/location", ""),
            "url": status.get("url", ""),
            "latest_revision": status.get("latestReadyRevisionName", ""),
            "traffic_allocation": traffic_allocation,
            "created": metadata.get("creationTimestamp", ""),
            "updated": metadata.get("annotations", {}).get("run.googleapis.com/lastModifier", ""),
            "ready": all(
                cond.get("status") == "True"
                for cond in status.get("conditions", [])
            ),
        }

        if detailed:
            # Add more details for single service describe
            template = spec.get("template", {})
            container = template.get("spec", {}).get("containers", [{}])[0]

            parsed["details"] = {
                "image": container.get("image", ""),
                "port": container.get("ports", [{}])[0].get("containerPort", 8080),
                "env_vars": [
                    {"name": e.get("name"), "value": e.get("value", "[secret]")}
                    for e in container.get("env", [])
                ],
                "resources": container.get("resources", {}),
                "scaling": {
                    "min_instances": template.get("metadata", {}).get("annotations", {}).get(
                        "autoscaling.knative.dev/minScale", "0"
                    ),
                    "max_instances": template.get("metadata", {}).get("annotations", {}).get(
                        "autoscaling.knative.dev/maxScale", "100"
                    ),
                },
                "vpc_connector": template.get("metadata", {}).get("annotations", {}).get(
                    "run.googleapis.com/vpc-access-connector", ""
                ),
                "service_account": template.get("spec", {}).get("serviceAccountName", ""),
            }

        return parsed

    def _get_revisions(self, project_id: str, region: str, service_name: str) -> List[Dict]:
        """Get revision history for a service"""
        cmd = [
            self._gcloud_path,
            "run",
            "revisions",
            "list",
            "--service", service_name,
            "--project", project_id,
            "--region", region,
            "--format", "json",
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            revisions = json.loads(result.stdout) if result.stdout else []

            return [
                {
                    "name": rev.get("metadata", {}).get("name", ""),
                    "created": rev.get("metadata", {}).get("creationTimestamp", ""),
                    "ready": rev.get("status", {}).get("conditions", [{}])[0].get("status") == "True",
                    "image": rev.get("spec", {}).get("containers", [{}])[0].get("image", ""),
                }
                for rev in revisions[:10]  # Limit to last 10 revisions
            ]
        except subprocess.CalledProcessError:
            return []


class CloudRunConfigReaderTool(BaseTool):
    """
    Read and analyze current Cloud Run service configuration.

    Extracts detailed configuration including:
    - Container settings (image, ports, env vars)
    - Scaling configuration
    - Resource limits (CPU, memory)
    - Networking (VPC, ingress)
    - Security settings (service account, secrets)
    """

    def __init__(self):
        self._gcloud_path = shutil.which("gcloud")
        metadata = ToolMetadata(
            name="cloud_run_config_reader",
            description="Read and analyze current Cloud Run service configuration",
            category="introspection",
            version="1.0.0",
            requires_auth=True,
        )
        super().__init__(metadata)

    def _validate_config(self):
        if not self._gcloud_path:
            raise RuntimeError("gcloud CLI not found")

    def _execute(
        self,
        project_id: str,
        region: str,
        service_name: str,
        output_format: str = "detailed",
    ) -> Dict[str, Any]:
        """
        Read service configuration.

        Args:
            project_id: GCP project ID
            region: Service region
            service_name: Name of the service
            output_format: 'detailed', 'yaml', or 'terraform' (for IaC export)

        Returns:
            Configuration in requested format
        """
        try:
            # Get service details
            cmd = [
                self._gcloud_path,
                "run",
                "services",
                "describe",
                service_name,
                "--project", project_id,
                "--region", region,
                "--format", "json",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            service = json.loads(result.stdout) if result.stdout else {}

            if output_format == "yaml":
                return self._export_yaml(service)
            elif output_format == "terraform":
                return self._export_terraform(project_id, region, service)
            else:
                return self._parse_detailed_config(service)

        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "error": f"Failed to read configuration: {e.stderr}",
            }

    def _parse_detailed_config(self, service: Dict) -> Dict[str, Any]:
        """Parse service into detailed configuration"""
        metadata = service.get("metadata", {})
        annotations = metadata.get("annotations", {})
        spec = service.get("spec", {})
        template = spec.get("template", {})
        template_metadata = template.get("metadata", {})
        template_annotations = template_metadata.get("annotations", {})
        template_spec = template.get("spec", {})
        container = template_spec.get("containers", [{}])[0]

        return {
            "success": True,
            "service_name": metadata.get("name", ""),
            "configuration": {
                "container": {
                    "image": container.get("image", ""),
                    "port": container.get("ports", [{}])[0].get("containerPort", 8080),
                    "command": container.get("command", []),
                    "args": container.get("args", []),
                },
                "environment": {
                    "variables": [
                        {
                            "name": e.get("name"),
                            "source": "secret" if e.get("valueFrom") else "literal",
                            "value": e.get("value") if e.get("value") else self._parse_secret_ref(e.get("valueFrom", {})),
                        }
                        for e in container.get("env", [])
                    ],
                },
                "resources": {
                    "cpu": container.get("resources", {}).get("limits", {}).get("cpu", "1"),
                    "memory": container.get("resources", {}).get("limits", {}).get("memory", "512Mi"),
                    "cpu_throttling": template_annotations.get("run.googleapis.com/cpu-throttling", "true"),
                },
                "scaling": {
                    "min_instances": int(template_annotations.get("autoscaling.knative.dev/minScale", "0")),
                    "max_instances": int(template_annotations.get("autoscaling.knative.dev/maxScale", "100")),
                    "concurrency": int(template_spec.get("containerConcurrency", 80)),
                },
                "networking": {
                    "ingress": annotations.get("run.googleapis.com/ingress", "all"),
                    "vpc_connector": template_annotations.get("run.googleapis.com/vpc-access-connector", ""),
                    "vpc_egress": template_annotations.get("run.googleapis.com/vpc-access-egress", ""),
                },
                "security": {
                    "service_account": template_spec.get("serviceAccountName", ""),
                    "binary_authorization": annotations.get("run.googleapis.com/binary-authorization", ""),
                },
                "metadata": {
                    "created": metadata.get("creationTimestamp", ""),
                    "generation": metadata.get("generation", 1),
                    "labels": metadata.get("labels", {}),
                },
            },
            "recommendations": self._generate_recommendations(service),
        }

    def _parse_secret_ref(self, value_from: Dict) -> str:
        """Parse secret reference"""
        secret_ref = value_from.get("secretKeyRef", {})
        return f"secret:{secret_ref.get('name', '')}:{secret_ref.get('key', '')}"

    def _generate_recommendations(self, service: Dict) -> List[str]:
        """Generate optimization recommendations based on config"""
        recommendations = []
        template = service.get("spec", {}).get("template", {})
        annotations = template.get("metadata", {}).get("annotations", {})
        container = template.get("spec", {}).get("containers", [{}])[0]

        # Check min instances
        min_instances = int(annotations.get("autoscaling.knative.dev/minScale", "0"))
        if min_instances == 0:
            recommendations.append(
                "Consider setting min_instances=1 to avoid cold starts for production workloads"
            )

        # Check memory
        memory = container.get("resources", {}).get("limits", {}).get("memory", "512Mi")
        if "256Mi" in memory or "128Mi" in memory:
            recommendations.append(
                "Low memory allocation may cause OOM errors under load"
            )

        # Check CPU throttling
        cpu_throttling = annotations.get("run.googleapis.com/cpu-throttling", "true")
        if cpu_throttling == "true":
            recommendations.append(
                "CPU throttling is enabled. Disable for consistent performance on CPU-intensive workloads"
            )

        # Check VPC connector
        vpc_connector = annotations.get("run.googleapis.com/vpc-access-connector", "")
        if not vpc_connector:
            recommendations.append(
                "No VPC connector configured. Add one for secure access to internal resources"
            )

        # Check service account
        service_account = template.get("spec", {}).get("serviceAccountName", "")
        if not service_account or service_account == "default":
            recommendations.append(
                "Using default service account. Create a dedicated SA with minimal permissions"
            )

        return recommendations

    def _export_yaml(self, service: Dict) -> Dict[str, Any]:
        """Export configuration as YAML (for kubectl apply)"""
        import yaml

        # Clean up service for export
        export_service = {
            "apiVersion": "serving.knative.dev/v1",
            "kind": "Service",
            "metadata": {
                "name": service.get("metadata", {}).get("name", ""),
                "labels": service.get("metadata", {}).get("labels", {}),
                "annotations": service.get("metadata", {}).get("annotations", {}),
            },
            "spec": service.get("spec", {}),
        }

        return {
            "success": True,
            "format": "yaml",
            "content": yaml.dump(export_service, default_flow_style=False),
        }

    def _export_terraform(self, project_id: str, region: str, service: Dict) -> Dict[str, Any]:
        """Export configuration as Terraform"""
        metadata = service.get("metadata", {})
        template = service.get("spec", {}).get("template", {})
        template_annotations = template.get("metadata", {}).get("annotations", {})
        template_spec = template.get("spec", {})
        container = template_spec.get("containers", [{}])[0]

        service_name = metadata.get("name", "my-service")

        tf_config = f'''# Terraform configuration exported from Cloud Run service
# Generated by AgentOS CloudRunConfigReaderTool

resource "google_cloud_run_v2_service" "{service_name.replace("-", "_")}" {{
  name     = "{service_name}"
  location = "{region}"
  project  = "{project_id}"

  template {{
    containers {{
      image = "{container.get("image", "")}"

      resources {{
        limits = {{
          cpu    = "{container.get("resources", {}).get("limits", {}).get("cpu", "1")}"
          memory = "{container.get("resources", {}).get("limits", {}).get("memory", "512Mi")}"
        }}
      }}
'''

        # Add environment variables
        for env in container.get("env", []):
            if env.get("value"):
                tf_config += f'''
      env {{
        name  = "{env.get("name")}"
        value = "{env.get("value")}"
      }}
'''

        tf_config += f'''
    }}

    scaling {{
      min_instance_count = {template_annotations.get("autoscaling.knative.dev/minScale", "0")}
      max_instance_count = {template_annotations.get("autoscaling.knative.dev/maxScale", "100")}
    }}
  }}
}}

# IAM binding for public access (if needed)
# resource "google_cloud_run_v2_service_iam_member" "{service_name.replace("-", "_")}_invoker" {{
#   project  = google_cloud_run_v2_service.{service_name.replace("-", "_")}.project
#   location = google_cloud_run_v2_service.{service_name.replace("-", "_")}.location
#   name     = google_cloud_run_v2_service.{service_name.replace("-", "_")}.name
#   role     = "roles/run.invoker"
#   member   = "allUsers"
# }}
'''

        return {
            "success": True,
            "format": "terraform",
            "content": tf_config,
        }


class RevisionInspectorTool(BaseTool):
    """
    Inspect and compare Cloud Run revisions.

    Capabilities:
    - List revision history
    - Compare two revisions (diff)
    - Identify configuration changes
    - Show deployment timeline
    """

    def __init__(self):
        self._gcloud_path = shutil.which("gcloud")
        metadata = ToolMetadata(
            name="revision_inspector",
            description="Inspect and compare Cloud Run revisions to understand changes",
            category="introspection",
            version="1.0.0",
            requires_auth=True,
        )
        super().__init__(metadata)

    def _validate_config(self):
        if not self._gcloud_path:
            raise RuntimeError("gcloud CLI not found")

    def _execute(
        self,
        project_id: str,
        region: str,
        service_name: str,
        action: str = "list",
        revision_a: Optional[str] = None,
        revision_b: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Inspect revisions.

        Args:
            project_id: GCP project ID
            region: Service region
            service_name: Name of the service
            action: 'list', 'describe', 'compare', or 'timeline'
            revision_a: First revision for comparison (or single revision to describe)
            revision_b: Second revision for comparison

        Returns:
            Revision information based on action
        """
        try:
            if action == "list":
                return self._list_revisions(project_id, region, service_name)
            elif action == "describe" and revision_a:
                return self._describe_revision(project_id, region, revision_a)
            elif action == "compare" and revision_a and revision_b:
                return self._compare_revisions(project_id, region, revision_a, revision_b)
            elif action == "timeline":
                return self._get_timeline(project_id, region, service_name)
            else:
                return {
                    "success": False,
                    "error": f"Invalid action '{action}' or missing required parameters",
                }
        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "error": f"Revision inspection failed: {e.stderr}",
            }

    def _list_revisions(self, project_id: str, region: str, service_name: str) -> Dict[str, Any]:
        """List all revisions for a service"""
        cmd = [
            self._gcloud_path,
            "run",
            "revisions",
            "list",
            "--service", service_name,
            "--project", project_id,
            "--region", region,
            "--format", "json",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        revisions = json.loads(result.stdout) if result.stdout else []

        parsed = []
        for rev in revisions:
            metadata = rev.get("metadata", {})
            status = rev.get("status", {})
            conditions = status.get("conditions", [])

            ready = any(
                c.get("type") == "Ready" and c.get("status") == "True"
                for c in conditions
            )

            parsed.append({
                "name": metadata.get("name", ""),
                "created": metadata.get("creationTimestamp", ""),
                "ready": ready,
                "active": status.get("conditions", [{}])[0].get("status") == "True",
                "image": rev.get("spec", {}).get("containers", [{}])[0].get("image", ""),
            })

        return {
            "success": True,
            "service": service_name,
            "revision_count": len(parsed),
            "revisions": parsed,
        }

    def _describe_revision(self, project_id: str, region: str, revision_name: str) -> Dict[str, Any]:
        """Get detailed info about a specific revision"""
        cmd = [
            self._gcloud_path,
            "run",
            "revisions",
            "describe",
            revision_name,
            "--project", project_id,
            "--region", region,
            "--format", "json",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        revision = json.loads(result.stdout) if result.stdout else {}

        spec = revision.get("spec", {})
        container = spec.get("containers", [{}])[0]
        metadata = revision.get("metadata", {})
        annotations = metadata.get("annotations", {})

        return {
            "success": True,
            "revision": {
                "name": metadata.get("name", ""),
                "created": metadata.get("creationTimestamp", ""),
                "container": {
                    "image": container.get("image", ""),
                    "port": container.get("ports", [{}])[0].get("containerPort", 8080),
                    "env_count": len(container.get("env", [])),
                },
                "resources": container.get("resources", {}).get("limits", {}),
                "scaling": {
                    "min": annotations.get("autoscaling.knative.dev/minScale", "0"),
                    "max": annotations.get("autoscaling.knative.dev/maxScale", "100"),
                },
                "concurrency": spec.get("containerConcurrency", 80),
            },
        }

    def _compare_revisions(
        self, project_id: str, region: str, revision_a: str, revision_b: str
    ) -> Dict[str, Any]:
        """Compare two revisions and show differences"""
        # Get both revisions
        rev_a = self._describe_revision(project_id, region, revision_a)
        rev_b = self._describe_revision(project_id, region, revision_b)

        if not rev_a.get("success") or not rev_b.get("success"):
            return {
                "success": False,
                "error": "Failed to retrieve one or both revisions",
            }

        a = rev_a["revision"]
        b = rev_b["revision"]

        # Compare configurations
        differences = []

        # Image
        if a["container"]["image"] != b["container"]["image"]:
            differences.append({
                "field": "container.image",
                "old": a["container"]["image"],
                "new": b["container"]["image"],
            })

        # Port
        if a["container"]["port"] != b["container"]["port"]:
            differences.append({
                "field": "container.port",
                "old": a["container"]["port"],
                "new": b["container"]["port"],
            })

        # Resources
        for resource in ["cpu", "memory"]:
            old_val = a.get("resources", {}).get(resource, "")
            new_val = b.get("resources", {}).get(resource, "")
            if old_val != new_val:
                differences.append({
                    "field": f"resources.{resource}",
                    "old": old_val,
                    "new": new_val,
                })

        # Scaling
        for scale in ["min", "max"]:
            old_val = a.get("scaling", {}).get(scale, "")
            new_val = b.get("scaling", {}).get(scale, "")
            if old_val != new_val:
                differences.append({
                    "field": f"scaling.{scale}",
                    "old": old_val,
                    "new": new_val,
                })

        # Concurrency
        if a.get("concurrency") != b.get("concurrency"):
            differences.append({
                "field": "concurrency",
                "old": a.get("concurrency"),
                "new": b.get("concurrency"),
            })

        return {
            "success": True,
            "comparison": {
                "revision_a": revision_a,
                "revision_b": revision_b,
                "difference_count": len(differences),
                "differences": differences,
                "summary": self._summarize_changes(differences),
            },
        }

    def _summarize_changes(self, differences: List[Dict]) -> str:
        """Generate human-readable summary of changes"""
        if not differences:
            return "No configuration differences found"

        summaries = []
        for diff in differences:
            field = diff["field"]
            if "image" in field:
                summaries.append(f"Container image updated")
            elif "cpu" in field:
                summaries.append(f"CPU limit changed: {diff['old']} → {diff['new']}")
            elif "memory" in field:
                summaries.append(f"Memory limit changed: {diff['old']} → {diff['new']}")
            elif "scaling" in field:
                summaries.append(f"Scaling {field.split('.')[-1]} changed: {diff['old']} → {diff['new']}")
            elif "concurrency" in field:
                summaries.append(f"Concurrency changed: {diff['old']} → {diff['new']}")
            else:
                summaries.append(f"{field} changed")

        return "; ".join(summaries)

    def _get_timeline(self, project_id: str, region: str, service_name: str) -> Dict[str, Any]:
        """Get deployment timeline for a service"""
        revisions = self._list_revisions(project_id, region, service_name)

        if not revisions.get("success"):
            return revisions

        # Sort by creation time
        sorted_revisions = sorted(
            revisions["revisions"],
            key=lambda x: x.get("created", ""),
        )

        timeline = []
        for i, rev in enumerate(sorted_revisions):
            event = {
                "revision": rev["name"],
                "timestamp": rev["created"],
                "status": "active" if rev["ready"] else "failed",
                "image_tag": rev["image"].split(":")[-1] if ":" in rev["image"] else "latest",
            }

            # Calculate time since previous deployment
            if i > 0:
                try:
                    prev_time = datetime.fromisoformat(sorted_revisions[i-1]["created"].replace("Z", "+00:00"))
                    curr_time = datetime.fromisoformat(rev["created"].replace("Z", "+00:00"))
                    delta = curr_time - prev_time
                    event["time_since_previous"] = str(delta)
                except (ValueError, KeyError):
                    event["time_since_previous"] = "unknown"

            timeline.append(event)

        return {
            "success": True,
            "service": service_name,
            "timeline": timeline,
            "deployment_frequency": self._calculate_frequency(sorted_revisions),
        }

    def _calculate_frequency(self, revisions: List[Dict]) -> str:
        """Calculate deployment frequency"""
        if len(revisions) < 2:
            return "insufficient data"

        try:
            first = datetime.fromisoformat(revisions[0]["created"].replace("Z", "+00:00"))
            last = datetime.fromisoformat(revisions[-1]["created"].replace("Z", "+00:00"))
            total_days = (last - first).days or 1
            deploys_per_day = len(revisions) / total_days

            if deploys_per_day >= 1:
                return f"{deploys_per_day:.1f} deployments per day"
            elif deploys_per_day >= 1/7:
                return f"{deploys_per_day * 7:.1f} deployments per week"
            else:
                return f"{deploys_per_day * 30:.1f} deployments per month"
        except (ValueError, KeyError):
            return "unable to calculate"


class HealthMonitorTool(BaseTool):
    """
    Monitor health status of Cloud Run services.

    Checks:
    - Service readiness
    - Health check status
    - Recent errors
    - Latency metrics
    - Instance status
    """

    def __init__(self):
        self._gcloud_path = shutil.which("gcloud")
        metadata = ToolMetadata(
            name="health_monitor",
            description="Monitor health status and metrics of Cloud Run services",
            category="introspection",
            version="1.0.0",
            requires_auth=True,
        )
        super().__init__(metadata)

    def _validate_config(self):
        if not self._gcloud_path:
            raise RuntimeError("gcloud CLI not found")

    def _execute(
        self,
        project_id: str,
        region: str,
        service_name: str,
        check_type: str = "full",
        time_range: str = "1h",
    ) -> Dict[str, Any]:
        """
        Check service health.

        Args:
            project_id: GCP project ID
            region: Service region
            service_name: Name of the service
            check_type: 'quick' (status only), 'full' (status + metrics + errors)
            time_range: Time range for metrics (e.g., '1h', '24h', '7d')

        Returns:
            Health status and metrics
        """
        try:
            health_report = {
                "success": True,
                "service": service_name,
                "checked_at": datetime.utcnow().isoformat() + "Z",
            }

            # Get service status
            status = self._check_service_status(project_id, region, service_name)
            health_report["status"] = status

            if check_type == "full":
                # Get recent errors from logs
                errors = self._get_recent_errors(project_id, service_name, time_range)
                health_report["recent_errors"] = errors

                # Get latency metrics
                metrics = self._get_metrics(project_id, service_name, time_range)
                health_report["metrics"] = metrics

                # Get instance info
                instances = self._get_instance_info(project_id, region, service_name)
                health_report["instances"] = instances

            # Overall health score
            health_report["health_score"] = self._calculate_health_score(health_report)
            health_report["recommendations"] = self._generate_health_recommendations(health_report)

            return health_report

        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "error": f"Health check failed: {e.stderr}",
            }

    def _check_service_status(self, project_id: str, region: str, service_name: str) -> Dict[str, Any]:
        """Check basic service status"""
        cmd = [
            self._gcloud_path,
            "run",
            "services",
            "describe",
            service_name,
            "--project", project_id,
            "--region", region,
            "--format", "json",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        service = json.loads(result.stdout) if result.stdout else {}

        status = service.get("status", {})
        conditions = status.get("conditions", [])

        # Parse conditions
        condition_status = {}
        for cond in conditions:
            cond_type = cond.get("type", "")
            cond_status = cond.get("status", "") == "True"
            condition_status[cond_type] = {
                "healthy": cond_status,
                "reason": cond.get("reason", ""),
                "message": cond.get("message", ""),
            }

        return {
            "url": status.get("url", ""),
            "latest_revision": status.get("latestReadyRevisionName", ""),
            "ready": condition_status.get("Ready", {}).get("healthy", False),
            "routes_ready": condition_status.get("RoutesReady", {}).get("healthy", False),
            "configuration_ready": condition_status.get("ConfigurationsReady", {}).get("healthy", False),
            "conditions": condition_status,
        }

    def _get_recent_errors(self, project_id: str, service_name: str, time_range: str) -> Dict[str, Any]:
        """Get recent errors from Cloud Logging"""
        # Parse time range
        hours = self._parse_time_range(time_range)

        cmd = [
            self._gcloud_path,
            "logging",
            "read",
            f'resource.type="cloud_run_revision" AND resource.labels.service_name="{service_name}" AND severity>=ERROR',
            "--project", project_id,
            "--limit", "50",
            "--freshness", f"{hours}h",
            "--format", "json",
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logs = json.loads(result.stdout) if result.stdout else []

            # Group errors by type
            error_types = {}
            for log in logs:
                msg = log.get("textPayload", "") or log.get("jsonPayload", {}).get("message", "")
                error_key = msg[:100] if msg else "Unknown error"

                if error_key not in error_types:
                    error_types[error_key] = {
                        "count": 0,
                        "first_seen": log.get("timestamp", ""),
                        "last_seen": log.get("timestamp", ""),
                        "sample": msg[:500],
                    }

                error_types[error_key]["count"] += 1
                error_types[error_key]["last_seen"] = log.get("timestamp", "")

            return {
                "total_errors": len(logs),
                "unique_errors": len(error_types),
                "time_range": time_range,
                "errors": list(error_types.values())[:10],  # Top 10 error types
            }
        except subprocess.CalledProcessError:
            return {
                "total_errors": 0,
                "error": "Unable to fetch logs",
            }

    def _get_metrics(self, project_id: str, service_name: str, time_range: str) -> Dict[str, Any]:
        """Get performance metrics"""
        # Note: Full metrics require Cloud Monitoring API
        # This provides a simplified version using gcloud

        hours = self._parse_time_range(time_range)

        return {
            "time_range": time_range,
            "note": "For detailed metrics, use Cloud Monitoring dashboard or API",
            "suggested_queries": [
                f"cloud.run.request_count{{service_name=\"{service_name}\"}}",
                f"cloud.run.request_latencies{{service_name=\"{service_name}\"}}",
                f"cloud.run.container/cpu/utilizations{{service_name=\"{service_name}\"}}",
                f"cloud.run.container/memory/utilizations{{service_name=\"{service_name}\"}}",
            ],
        }

    def _get_instance_info(self, project_id: str, region: str, service_name: str) -> Dict[str, Any]:
        """Get current instance information"""
        # Get current revision details
        cmd = [
            self._gcloud_path,
            "run",
            "services",
            "describe",
            service_name,
            "--project", project_id,
            "--region", region,
            "--format", "json",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        service = json.loads(result.stdout) if result.stdout else {}

        template = service.get("spec", {}).get("template", {})
        annotations = template.get("metadata", {}).get("annotations", {})

        return {
            "min_instances": int(annotations.get("autoscaling.knative.dev/minScale", "0")),
            "max_instances": int(annotations.get("autoscaling.knative.dev/maxScale", "100")),
            "note": "Actual running instance count available via Cloud Monitoring",
        }

    def _parse_time_range(self, time_range: str) -> int:
        """Parse time range string to hours"""
        if time_range.endswith("h"):
            return int(time_range[:-1])
        elif time_range.endswith("d"):
            return int(time_range[:-1]) * 24
        elif time_range.endswith("m"):
            return max(1, int(time_range[:-1]) // 60)
        return 1

    def _calculate_health_score(self, report: Dict) -> Dict[str, Any]:
        """Calculate overall health score (0-100)"""
        score = 100
        issues = []

        status = report.get("status", {})

        # Check readiness
        if not status.get("ready"):
            score -= 50
            issues.append("Service not ready")

        if not status.get("routes_ready"):
            score -= 20
            issues.append("Routes not ready")

        if not status.get("configuration_ready"):
            score -= 20
            issues.append("Configuration not ready")

        # Check errors
        errors = report.get("recent_errors", {})
        error_count = errors.get("total_errors", 0)
        if error_count > 100:
            score -= 30
            issues.append(f"High error rate: {error_count} errors")
        elif error_count > 10:
            score -= 15
            issues.append(f"Moderate errors: {error_count} errors")
        elif error_count > 0:
            score -= 5
            issues.append(f"Some errors: {error_count} errors")

        return {
            "score": max(0, score),
            "rating": "healthy" if score >= 80 else "degraded" if score >= 50 else "unhealthy",
            "issues": issues,
        }

    def _generate_health_recommendations(self, report: Dict) -> List[str]:
        """Generate health improvement recommendations"""
        recommendations = []

        status = report.get("status", {})
        health_score = report.get("health_score", {})
        errors = report.get("recent_errors", {})
        instances = report.get("instances", {})

        # Check for cold start potential
        if instances.get("min_instances", 0) == 0:
            recommendations.append(
                "Set min_instances > 0 to avoid cold starts and improve latency"
            )

        # Check error patterns
        if errors.get("total_errors", 0) > 10:
            recommendations.append(
                "Review error logs and implement error handling or fix root causes"
            )

        # Check if service degraded
        if health_score.get("rating") == "degraded":
            recommendations.append(
                "Service is degraded. Check conditions and recent changes"
            )

        # Check routes
        if not status.get("routes_ready"):
            recommendations.append(
                "Routes not ready. Check domain mapping and traffic configuration"
            )

        if not recommendations:
            recommendations.append("Service appears healthy. No immediate actions needed.")

        return recommendations


class ResourceMetricsTool(BaseTool):
    """
    Read resource usage metrics for Cloud Run services.

    Metrics:
    - CPU utilization
    - Memory utilization
    - Request count
    - Request latency
    - Instance count
    - Billable time
    """

    def __init__(self):
        self._gcloud_path = shutil.which("gcloud")
        metadata = ToolMetadata(
            name="resource_metrics",
            description="Read CPU, memory, request, and cost metrics for Cloud Run services",
            category="introspection",
            version="1.0.0",
            requires_auth=True,
        )
        super().__init__(metadata)

    def _validate_config(self):
        if not self._gcloud_path:
            raise RuntimeError("gcloud CLI not found")

    def _execute(
        self,
        project_id: str,
        service_name: str,
        metric_type: str = "all",
        time_range: str = "1h",
        aggregation: str = "mean",
    ) -> Dict[str, Any]:
        """
        Get resource metrics.

        Args:
            project_id: GCP project ID
            service_name: Name of the service
            metric_type: 'cpu', 'memory', 'requests', 'latency', 'cost', or 'all'
            time_range: Time range (e.g., '1h', '24h', '7d')
            aggregation: 'mean', 'max', 'min', or 'sum'

        Returns:
            Resource metrics data
        """
        try:
            metrics = {
                "success": True,
                "service": service_name,
                "time_range": time_range,
                "aggregation": aggregation,
            }

            if metric_type in ["cpu", "all"]:
                metrics["cpu"] = self._get_cpu_metrics(project_id, service_name, time_range)

            if metric_type in ["memory", "all"]:
                metrics["memory"] = self._get_memory_metrics(project_id, service_name, time_range)

            if metric_type in ["requests", "all"]:
                metrics["requests"] = self._get_request_metrics(project_id, service_name, time_range)

            if metric_type in ["latency", "all"]:
                metrics["latency"] = self._get_latency_info(project_id, service_name, time_range)

            if metric_type in ["cost", "all"]:
                metrics["cost"] = self._estimate_cost(project_id, service_name, time_range)

            # Add optimization suggestions
            metrics["optimization_suggestions"] = self._generate_optimizations(metrics)

            return metrics

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get metrics: {str(e)}",
            }

    def _get_cpu_metrics(self, project_id: str, service_name: str, time_range: str) -> Dict[str, Any]:
        """Get CPU utilization metrics"""
        # Note: Full metrics require Cloud Monitoring API client library
        # This provides guidance on how to query
        return {
            "metric": "run.googleapis.com/container/cpu/utilizations",
            "description": "Container CPU utilization",
            "unit": "ratio (0-1)",
            "query_command": f"""gcloud monitoring read \\
  "metric.type=\\"run.googleapis.com/container/cpu/utilizations\\" \\
   AND resource.labels.service_name=\\"{service_name}\\"" \\
  --project={project_id} \\
  --interval-start-time=$(date -u -d '-{time_range}' +%Y-%m-%dT%H:%M:%SZ)""",
            "dashboard_link": f"https://console.cloud.google.com/run/detail/{service_name}/metrics?project={project_id}",
        }

    def _get_memory_metrics(self, project_id: str, service_name: str, time_range: str) -> Dict[str, Any]:
        """Get memory utilization metrics"""
        return {
            "metric": "run.googleapis.com/container/memory/utilizations",
            "description": "Container memory utilization",
            "unit": "ratio (0-1)",
            "query_command": f"""gcloud monitoring read \\
  "metric.type=\\"run.googleapis.com/container/memory/utilizations\\" \\
   AND resource.labels.service_name=\\"{service_name}\\"" \\
  --project={project_id}""",
            "dashboard_link": f"https://console.cloud.google.com/run/detail/{service_name}/metrics?project={project_id}",
        }

    def _get_request_metrics(self, project_id: str, service_name: str, time_range: str) -> Dict[str, Any]:
        """Get request count and rate metrics"""
        return {
            "metrics": {
                "request_count": "run.googleapis.com/request_count",
                "request_latencies": "run.googleapis.com/request_latencies",
            },
            "description": "Request count and latency distribution",
            "query_command": f"""gcloud monitoring read \\
  "metric.type=\\"run.googleapis.com/request_count\\" \\
   AND resource.labels.service_name=\\"{service_name}\\"" \\
  --project={project_id}""",
            "dashboard_link": f"https://console.cloud.google.com/run/detail/{service_name}/metrics?project={project_id}",
        }

    def _get_latency_info(self, project_id: str, service_name: str, time_range: str) -> Dict[str, Any]:
        """Get latency percentile information"""
        return {
            "metric": "run.googleapis.com/request_latencies",
            "description": "Request latency distribution (p50, p95, p99)",
            "unit": "milliseconds",
            "percentiles": ["p50", "p95", "p99"],
            "note": "Use Cloud Monitoring dashboard for percentile breakdowns",
            "dashboard_link": f"https://console.cloud.google.com/run/detail/{service_name}/metrics?project={project_id}",
        }

    def _estimate_cost(self, project_id: str, service_name: str, time_range: str) -> Dict[str, Any]:
        """Estimate service cost"""
        # Cloud Run pricing (as of 2024)
        pricing = {
            "cpu_per_second": 0.00002400,  # per vCPU-second
            "memory_per_gib_second": 0.00000250,  # per GiB-second
            "requests_per_million": 0.40,  # per million requests
        }

        return {
            "pricing_model": "per-use (CPU, memory, requests)",
            "pricing_reference": pricing,
            "note": "Actual costs depend on usage. Check Cloud Billing for accurate data.",
            "cost_explorer_link": f"https://console.cloud.google.com/billing/reports?project={project_id}",
            "optimization_tips": [
                "Set min_instances=0 for dev/staging to reduce idle costs",
                "Use CPU throttling (enabled by default) for request-based workloads",
                "Right-size memory allocation based on actual usage",
                "Consider committed use discounts for production workloads",
            ],
        }

    def _generate_optimizations(self, metrics: Dict) -> List[str]:
        """Generate resource optimization suggestions"""
        suggestions = []

        suggestions.append(
            "Review CPU utilization - if consistently < 50%, consider reducing CPU allocation"
        )
        suggestions.append(
            "Review memory utilization - if consistently < 50%, consider reducing memory allocation"
        )
        suggestions.append(
            "If p99 latency > 1s, consider increasing min_instances to reduce cold starts"
        )
        suggestions.append(
            "For batch workloads, consider using Cloud Run jobs instead of services"
        )

        return suggestions
