"""Scalability Tools - Auto-Scaling, Traffic Splitting, Load Balancer"""

import subprocess
import shutil
import json
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Type-Safe Models
# =============================================================================

class AutoScalingResult(BaseModel):
    """Result of auto-scaling configuration"""
    success: bool
    service_name: Optional[str] = None
    min_instances: Optional[int] = None
    max_instances: Optional[int] = None
    cpu_threshold: Optional[int] = None
    concurrency: Optional[int] = None
    message: str = ""
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class TrafficSplitResult(BaseModel):
    """Result of traffic splitting configuration"""
    success: bool
    service_name: Optional[str] = None
    revisions: Dict[str, int] = Field(default_factory=dict)  # revision: percentage
    strategy: Optional[str] = None  # canary, blue_green, gradual
    message: str = ""
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class LoadBalancerResult(BaseModel):
    """Result of load balancer configuration"""
    success: bool
    name: Optional[str] = None
    ip_address: Optional[str] = None
    backends: List[str] = Field(default_factory=list)
    health_check: Optional[str] = None
    ssl_enabled: bool = False
    message: str = ""
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class HealthCheckResult(BaseModel):
    """Result of health check configuration"""
    success: bool
    name: Optional[str] = None
    path: Optional[str] = None
    port: Optional[int] = None
    interval_sec: Optional[int] = None
    timeout_sec: Optional[int] = None
    healthy_threshold: Optional[int] = None
    unhealthy_threshold: Optional[int] = None
    message: str = ""
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Auto-Scaling Configuration Tool
# =============================================================================

class AutoScalingConfigTool(BaseTool):
    """Configure auto-scaling for Cloud Run services

    Features:
    - Min/max instance configuration
    - CPU-based scaling thresholds
    - Concurrency limits
    - Cold start optimization
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="auto_scaling_config",
                description="Configure auto-scaling for Cloud Run services",
                category="scalability",
                version="1.0.0",
                requires_auth=True,
            )
        )
        self._gcloud_path = shutil.which("gcloud")

    def _execute(
        self,
        service_name: str,
        region: str = "us-central1",
        project_id: Optional[str] = None,
        min_instances: int = 0,
        max_instances: int = 100,
        cpu_throttling: bool = True,
        concurrency: int = 80,
        cpu_limit: str = "1000m",
        memory_limit: str = "512Mi",
        startup_cpu_boost: bool = True,
    ) -> str:
        """Configure auto-scaling for a Cloud Run service"""

        if not self._gcloud_path:
            return AutoScalingResult(
                success=False,
                error="gcloud CLI not found"
            ).to_json()

        try:
            cmd = [
                self._gcloud_path, "run", "services", "update", service_name,
                f"--region={region}",
                f"--min-instances={min_instances}",
                f"--max-instances={max_instances}",
                f"--concurrency={concurrency}",
                f"--cpu={cpu_limit}",
                f"--memory={memory_limit}",
            ]

            if project_id:
                cmd.append(f"--project={project_id}")

            if not cpu_throttling:
                cmd.append("--no-cpu-throttling")

            if startup_cpu_boost:
                cmd.append("--cpu-boost")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode != 0:
                return AutoScalingResult(
                    success=False,
                    service_name=service_name,
                    error=result.stderr
                ).to_json()

            return AutoScalingResult(
                success=True,
                service_name=service_name,
                min_instances=min_instances,
                max_instances=max_instances,
                concurrency=concurrency,
                message=f"Auto-scaling configured: {min_instances}-{max_instances} instances, concurrency={concurrency}"
            ).to_json()

        except Exception as e:
            return AutoScalingResult(
                success=False,
                error=str(e)
            ).to_json()


# =============================================================================
# Traffic Splitting Tool
# =============================================================================

class TrafficSplittingTool(BaseTool):
    """Configure traffic splitting for safe deployments

    Strategies:
    - Canary: Gradual rollout (5% → 25% → 50% → 100%)
    - Blue/Green: Instant switch between versions
    - Gradual: Custom percentage splits
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="traffic_splitting",
                description="Configure traffic splitting for canary/blue-green deployments",
                category="scalability",
                version="1.0.0",
                requires_auth=True,
            )
        )
        self._gcloud_path = shutil.which("gcloud")

    def _execute(
        self,
        service_name: str,
        region: str = "us-central1",
        project_id: Optional[str] = None,
        strategy: str = "canary",  # canary, blue_green, custom
        new_revision: Optional[str] = None,
        old_revision: Optional[str] = None,
        new_traffic_percent: int = 10,  # For canary
        custom_splits: Optional[Dict[str, int]] = None,  # For custom
    ) -> str:
        """Configure traffic splitting between revisions"""

        if not self._gcloud_path:
            return TrafficSplitResult(
                success=False,
                error="gcloud CLI not found"
            ).to_json()

        try:
            # Get current revisions if not specified
            if not new_revision or not old_revision:
                revisions = self._get_revisions(service_name, region, project_id)
                if len(revisions) < 2 and strategy != "custom":
                    return TrafficSplitResult(
                        success=False,
                        error="Need at least 2 revisions for traffic splitting"
                    ).to_json()
                if not new_revision and revisions:
                    new_revision = revisions[0]
                if not old_revision and len(revisions) > 1:
                    old_revision = revisions[1]

            # Build traffic split command
            if strategy == "canary":
                splits = {
                    new_revision: new_traffic_percent,
                    old_revision: 100 - new_traffic_percent
                }
            elif strategy == "blue_green":
                # Instant switch to new revision
                splits = {new_revision: 100}
            elif strategy == "custom" and custom_splits:
                splits = custom_splits
            else:
                return TrafficSplitResult(
                    success=False,
                    error=f"Invalid strategy: {strategy}"
                ).to_json()

            # Build --to-revisions argument
            revisions_arg = ",".join(f"{rev}={pct}" for rev, pct in splits.items())

            cmd = [
                self._gcloud_path, "run", "services", "update-traffic", service_name,
                f"--region={region}",
                f"--to-revisions={revisions_arg}",
            ]

            if project_id:
                cmd.append(f"--project={project_id}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                return TrafficSplitResult(
                    success=False,
                    service_name=service_name,
                    error=result.stderr
                ).to_json()

            return TrafficSplitResult(
                success=True,
                service_name=service_name,
                revisions=splits,
                strategy=strategy,
                message=f"Traffic split configured: {splits}"
            ).to_json()

        except Exception as e:
            return TrafficSplitResult(
                success=False,
                error=str(e)
            ).to_json()

    def _get_revisions(self, service: str, region: str, project_id: Optional[str]) -> List[str]:
        """Get list of revisions for a service"""
        cmd = [
            self._gcloud_path, "run", "revisions", "list",
            f"--service={service}",
            f"--region={region}",
            "--format=value(REVISION)",
            "--sort-by=~CREATED",
            "--limit=5",
        ]

        if project_id:
            cmd.append(f"--project={project_id}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return []

        return [r.strip() for r in result.stdout.strip().split("\n") if r.strip()]


# =============================================================================
# Rollback Tool
# =============================================================================

class RollbackTool(BaseTool):
    """Rollback to previous revisions

    Features:
    - Instant rollback to previous version
    - Rollback to specific revision
    - Traffic-based rollback (gradual)
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="rollback",
                description="Rollback Cloud Run service to previous revision",
                category="scalability",
                version="1.0.0",
                requires_auth=True,
            )
        )
        self._gcloud_path = shutil.which("gcloud")

    def _execute(
        self,
        service_name: str,
        region: str = "us-central1",
        project_id: Optional[str] = None,
        revision: Optional[str] = None,  # Specific revision or None for previous
        instant: bool = True,  # Instant rollback vs gradual
    ) -> str:
        """Rollback to a previous revision"""

        if not self._gcloud_path:
            return TrafficSplitResult(
                success=False,
                error="gcloud CLI not found"
            ).to_json()

        try:
            # Get previous revision if not specified
            if not revision:
                revisions = self._get_revisions(service_name, region, project_id)
                if len(revisions) < 2:
                    return TrafficSplitResult(
                        success=False,
                        error="No previous revision available for rollback"
                    ).to_json()
                revision = revisions[1]  # Second most recent

            # Rollback by setting 100% traffic to target revision
            cmd = [
                self._gcloud_path, "run", "services", "update-traffic", service_name,
                f"--region={region}",
                f"--to-revisions={revision}=100",
            ]

            if project_id:
                cmd.append(f"--project={project_id}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                return TrafficSplitResult(
                    success=False,
                    error=result.stderr
                ).to_json()

            return TrafficSplitResult(
                success=True,
                service_name=service_name,
                revisions={revision: 100},
                strategy="rollback",
                message=f"Rolled back to revision: {revision}"
            ).to_json()

        except Exception as e:
            return TrafficSplitResult(
                success=False,
                error=str(e)
            ).to_json()

    def _get_revisions(self, service: str, region: str, project_id: Optional[str]) -> List[str]:
        """Get list of revisions"""
        cmd = [
            self._gcloud_path, "run", "revisions", "list",
            f"--service={service}",
            f"--region={region}",
            "--format=value(REVISION)",
            "--sort-by=~CREATED",
            "--limit=5",
        ]

        if project_id:
            cmd.append(f"--project={project_id}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return []

        return [r.strip() for r in result.stdout.strip().split("\n") if r.strip()]


# =============================================================================
# Load Balancer Configuration Tool
# =============================================================================

class LoadBalancerConfigTool(BaseTool):
    """Configure HTTPS load balancer for Cloud Run

    Features:
    - Global HTTPS load balancer
    - Managed SSL certificates
    - Health checks
    - CDN integration
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="load_balancer_config",
                description="Configure HTTPS load balancer with SSL and health checks",
                category="scalability",
                version="1.0.0",
                requires_auth=True,
            )
        )
        self._gcloud_path = shutil.which("gcloud")

    def _execute(
        self,
        name: str,
        backend_service: str,
        region: str = "us-central1",
        project_id: Optional[str] = None,
        domains: Optional[List[str]] = None,
        enable_cdn: bool = False,
        enable_ssl: bool = True,
        health_check_path: str = "/health",
    ) -> str:
        """Configure load balancer for Cloud Run service"""

        if not self._gcloud_path:
            return LoadBalancerResult(
                success=False,
                error="gcloud CLI not found"
            ).to_json()

        try:
            steps_completed = []

            # Step 1: Create NEG (Network Endpoint Group) for serverless
            neg_name = f"{name}-neg"
            cmd = [
                self._gcloud_path, "compute", "network-endpoint-groups", "create", neg_name,
                f"--region={region}",
                "--network-endpoint-type=serverless",
                f"--cloud-run-service={backend_service}",
            ]
            if project_id:
                cmd.append(f"--project={project_id}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                steps_completed.append("NEG created")
            elif "already exists" not in result.stderr:
                return LoadBalancerResult(success=False, error=f"NEG creation failed: {result.stderr}").to_json()

            # Step 2: Create backend service
            backend_name = f"{name}-backend"
            cmd = [
                self._gcloud_path, "compute", "backend-services", "create", backend_name,
                "--global",
                "--protocol=HTTP",
            ]
            if enable_cdn:
                cmd.append("--enable-cdn")
            if project_id:
                cmd.append(f"--project={project_id}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                steps_completed.append("Backend service created")

            # Step 3: Add NEG to backend service
            cmd = [
                self._gcloud_path, "compute", "backend-services", "add-backend", backend_name,
                "--global",
                f"--network-endpoint-group={neg_name}",
                f"--network-endpoint-group-region={region}",
            ]
            if project_id:
                cmd.append(f"--project={project_id}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                steps_completed.append("Backend added to service")

            # Step 4: Create URL map
            url_map_name = f"{name}-url-map"
            cmd = [
                self._gcloud_path, "compute", "url-maps", "create", url_map_name,
                f"--default-service={backend_name}",
                "--global",
            ]
            if project_id:
                cmd.append(f"--project={project_id}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                steps_completed.append("URL map created")

            # Step 5: Create SSL certificate if domains provided
            cert_name = None
            if enable_ssl and domains:
                cert_name = f"{name}-cert"
                cmd = [
                    self._gcloud_path, "compute", "ssl-certificates", "create", cert_name,
                    f"--domains={','.join(domains)}",
                    "--global",
                ]
                if project_id:
                    cmd.append(f"--project={project_id}")

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    steps_completed.append("SSL certificate created")

            # Step 6: Create HTTPS proxy
            proxy_name = f"{name}-https-proxy"
            cmd = [
                self._gcloud_path, "compute", "target-https-proxies", "create", proxy_name,
                f"--url-map={url_map_name}",
                "--global",
            ]
            if cert_name:
                cmd.append(f"--ssl-certificates={cert_name}")
            if project_id:
                cmd.append(f"--project={project_id}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                steps_completed.append("HTTPS proxy created")

            # Step 7: Create forwarding rule (assigns IP)
            fwd_rule_name = f"{name}-https-rule"
            cmd = [
                self._gcloud_path, "compute", "forwarding-rules", "create", fwd_rule_name,
                "--global",
                f"--target-https-proxy={proxy_name}",
                "--ports=443",
            ]
            if project_id:
                cmd.append(f"--project={project_id}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                steps_completed.append("Forwarding rule created")

            # Get the assigned IP
            ip_address = self._get_forwarding_rule_ip(fwd_rule_name, project_id)

            return LoadBalancerResult(
                success=True,
                name=name,
                ip_address=ip_address,
                backends=[backend_service],
                ssl_enabled=enable_ssl,
                message=f"Load balancer created. Steps: {', '.join(steps_completed)}"
            ).to_json()

        except Exception as e:
            return LoadBalancerResult(
                success=False,
                error=str(e)
            ).to_json()

    def _get_forwarding_rule_ip(self, rule_name: str, project_id: Optional[str]) -> Optional[str]:
        """Get IP address of forwarding rule"""
        cmd = [
            self._gcloud_path, "compute", "forwarding-rules", "describe", rule_name,
            "--global",
            "--format=value(IPAddress)",
        ]
        if project_id:
            cmd.append(f"--project={project_id}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout.strip() if result.returncode == 0 else None


# =============================================================================
# Health Check Configuration Tool
# =============================================================================

class HealthCheckConfigTool(BaseTool):
    """Configure health checks for services

    Features:
    - HTTP/HTTPS health checks
    - Custom paths and ports
    - Threshold configuration
    - Startup probes
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="health_check_config",
                description="Configure health checks for load-balanced services",
                category="scalability",
                version="1.0.0",
                requires_auth=True,
            )
        )
        self._gcloud_path = shutil.which("gcloud")

    def _execute(
        self,
        name: str,
        project_id: Optional[str] = None,
        check_type: str = "http",  # http, https, tcp
        request_path: str = "/health",
        port: int = 8080,
        check_interval_sec: int = 10,
        timeout_sec: int = 5,
        healthy_threshold: int = 2,
        unhealthy_threshold: int = 3,
    ) -> str:
        """Configure health check"""

        if not self._gcloud_path:
            return HealthCheckResult(
                success=False,
                error="gcloud CLI not found"
            ).to_json()

        try:
            cmd = [
                self._gcloud_path, "compute", "health-checks", "create", check_type, name,
                f"--request-path={request_path}",
                f"--port={port}",
                f"--check-interval={check_interval_sec}s",
                f"--timeout={timeout_sec}s",
                f"--healthy-threshold={healthy_threshold}",
                f"--unhealthy-threshold={unhealthy_threshold}",
                "--global",
            ]

            if project_id:
                cmd.append(f"--project={project_id}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                return HealthCheckResult(
                    success=False,
                    error=result.stderr
                ).to_json()

            return HealthCheckResult(
                success=True,
                name=name,
                path=request_path,
                port=port,
                interval_sec=check_interval_sec,
                timeout_sec=timeout_sec,
                healthy_threshold=healthy_threshold,
                unhealthy_threshold=unhealthy_threshold,
                message=f"Health check '{name}' created"
            ).to_json()

        except Exception as e:
            return HealthCheckResult(
                success=False,
                error=str(e)
            ).to_json()
