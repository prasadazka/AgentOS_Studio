"""CI/CD Pipeline Tools - Cloud Build Triggers, GitHub Actions, Test Runner"""

import subprocess
import shutil
import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import ToolExecutionError, ErrorCode
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Type-Safe Models
# =============================================================================

class CloudBuildTriggerResult(BaseModel):
    """Result of Cloud Build trigger operations"""
    success: bool
    trigger_id: Optional[str] = None
    trigger_name: Optional[str] = None
    project_id: Optional[str] = None
    repo_name: Optional[str] = None
    branch_pattern: Optional[str] = None
    build_config: Optional[str] = None
    message: str = ""
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class GitHubActionsResult(BaseModel):
    """Result of GitHub Actions workflow generation"""
    success: bool
    workflow_file: Optional[str] = None
    workflow_name: Optional[str] = None
    triggers: List[str] = Field(default_factory=list)
    jobs: List[str] = Field(default_factory=list)
    message: str = ""
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class TestRunnerResult(BaseModel):
    """Result of test execution"""
    success: bool
    framework: Optional[str] = None
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    tests_skipped: int = 0
    coverage: Optional[float] = None
    duration: Optional[float] = None
    output: Optional[str] = None
    message: str = ""
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Cloud Build Trigger Tool
# =============================================================================

class CloudBuildTriggerTool(BaseTool):
    """Create and manage Cloud Build triggers for CI/CD pipelines

    Operations:
    - create: Create a new build trigger
    - list: List existing triggers
    - delete: Delete a trigger
    - run: Manually run a trigger
    """

    def __init__(self):
        self._gcloud_path = shutil.which("gcloud")
        metadata = ToolMetadata(
            name="cloud_build_trigger",
            description="Create and manage Cloud Build triggers for automated CI/CD",
            category="cicd",
            version="1.0.0",
            requires_auth=True,
        )
        super().__init__(metadata)

    def _validate_config(self):
        if not self._gcloud_path:
            logger.warning("gcloud CLI not found - Cloud Build triggers will fail")

    def _execute(
        self,
        operation: str = "create",
        project_id: Optional[str] = None,
        trigger_name: Optional[str] = None,
        repo_owner: Optional[str] = None,
        repo_name: Optional[str] = None,
        branch_pattern: str = "^main$",
        build_config: str = "cloudbuild.yaml",
        trigger_id: Optional[str] = None,
        substitutions: Optional[Dict[str, str]] = None,
    ) -> str:
        """Execute Cloud Build trigger operations"""

        if not self._gcloud_path:
            return CloudBuildTriggerResult(
                success=False,
                error="gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
            ).to_json()

        try:
            if operation == "create":
                return self._create_trigger(
                    project_id, trigger_name, repo_owner, repo_name,
                    branch_pattern, build_config, substitutions
                )
            elif operation == "list":
                return self._list_triggers(project_id)
            elif operation == "delete":
                return self._delete_trigger(project_id, trigger_id or trigger_name)
            elif operation == "run":
                return self._run_trigger(project_id, trigger_id or trigger_name, branch_pattern)
            else:
                return CloudBuildTriggerResult(
                    success=False,
                    error=f"Unknown operation: {operation}. Use: create, list, delete, run"
                ).to_json()

        except subprocess.CalledProcessError as e:
            return CloudBuildTriggerResult(
                success=False,
                error=f"gcloud command failed: {e.stderr or str(e)}"
            ).to_json()
        except Exception as e:
            return CloudBuildTriggerResult(
                success=False,
                error=str(e)
            ).to_json()

    def _create_trigger(
        self,
        project_id: Optional[str],
        trigger_name: Optional[str],
        repo_owner: Optional[str],
        repo_name: Optional[str],
        branch_pattern: str,
        build_config: str,
        substitutions: Optional[Dict[str, str]],
    ) -> str:
        """Create a new Cloud Build trigger"""

        if not all([trigger_name, repo_owner, repo_name]):
            return CloudBuildTriggerResult(
                success=False,
                error="trigger_name, repo_owner, and repo_name are required"
            ).to_json()

        cmd = [
            self._gcloud_path, "builds", "triggers", "create", "github",
            f"--name={trigger_name}",
            f"--repo-owner={repo_owner}",
            f"--repo-name={repo_name}",
            f"--branch-pattern={branch_pattern}",
            f"--build-config={build_config}",
            "--format=json",
        ]

        if project_id:
            cmd.append(f"--project={project_id}")

        if substitutions:
            subs_str = ",".join(f"{k}={v}" for k, v in substitutions.items())
            cmd.append(f"--substitutions={subs_str}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            return CloudBuildTriggerResult(
                success=False,
                trigger_name=trigger_name,
                error=result.stderr
            ).to_json()

        try:
            data = json.loads(result.stdout)
            return CloudBuildTriggerResult(
                success=True,
                trigger_id=data.get("id"),
                trigger_name=trigger_name,
                project_id=project_id,
                repo_name=repo_name,
                branch_pattern=branch_pattern,
                build_config=build_config,
                message=f"Created trigger '{trigger_name}' successfully"
            ).to_json()
        except json.JSONDecodeError:
            return CloudBuildTriggerResult(
                success=True,
                trigger_name=trigger_name,
                message=f"Created trigger '{trigger_name}'"
            ).to_json()

    def _list_triggers(self, project_id: Optional[str]) -> str:
        """List existing triggers"""
        cmd = [self._gcloud_path, "builds", "triggers", "list", "--format=json"]
        if project_id:
            cmd.append(f"--project={project_id}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return CloudBuildTriggerResult(
                success=False,
                error=result.stderr
            ).to_json()

        return result.stdout

    def _delete_trigger(self, project_id: Optional[str], trigger_id: str) -> str:
        """Delete a trigger"""
        if not trigger_id:
            return CloudBuildTriggerResult(
                success=False,
                error="trigger_id or trigger_name required"
            ).to_json()

        cmd = [self._gcloud_path, "builds", "triggers", "delete", trigger_id, "--quiet"]
        if project_id:
            cmd.append(f"--project={project_id}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return CloudBuildTriggerResult(
                success=False,
                error=result.stderr
            ).to_json()

        return CloudBuildTriggerResult(
            success=True,
            trigger_id=trigger_id,
            message=f"Deleted trigger '{trigger_id}'"
        ).to_json()

    def _run_trigger(self, project_id: Optional[str], trigger_id: str, branch: str) -> str:
        """Manually run a trigger"""
        if not trigger_id:
            return CloudBuildTriggerResult(
                success=False,
                error="trigger_id required"
            ).to_json()

        cmd = [
            self._gcloud_path, "builds", "triggers", "run", trigger_id,
            f"--branch={branch.strip('^$')}",
            "--format=json"
        ]
        if project_id:
            cmd.append(f"--project={project_id}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            return CloudBuildTriggerResult(
                success=False,
                error=result.stderr
            ).to_json()

        return CloudBuildTriggerResult(
            success=True,
            trigger_id=trigger_id,
            message=f"Triggered build for '{trigger_id}'"
        ).to_json()


# =============================================================================
# GitHub Actions Generator Tool
# =============================================================================

class GitHubActionsGeneratorTool(BaseTool):
    """Generate GitHub Actions workflow files for CI/CD

    Supports:
    - Python (pytest, pip)
    - Node.js (npm, yarn)
    - Docker builds
    - GCP deployments
    """

    # Workflow templates
    PYTHON_WORKFLOW = """name: {name}

on:
  push:
    branches: [{branches}]
  pull_request:
    branches: [{branches}]

env:
  PYTHON_VERSION: "{python_version}"

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{{{ env.PYTHON_VERSION }}}}
          cache: 'pip'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest pytest-cov

      - name: Run tests
        run: pytest --cov=. --cov-report=xml

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml

  {deploy_job}
"""

    NODEJS_WORKFLOW = """name: {name}

on:
  push:
    branches: [{branches}]
  pull_request:
    branches: [{branches}]

env:
  NODE_VERSION: "{node_version}"

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: ${{{{ env.NODE_VERSION }}}}
          cache: 'npm'

      - name: Install dependencies
        run: npm ci

      - name: Run linter
        run: npm run lint --if-present

      - name: Run tests
        run: npm test

  {deploy_job}
"""

    GCP_DEPLOY_JOB = """deploy:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'

    permissions:
      contents: read
      id-token: write

    steps:
      - uses: actions/checkout@v4

      - name: Authenticate to Google Cloud
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{{{ secrets.WIF_PROVIDER }}}}
          service_account: ${{{{ secrets.WIF_SERVICE_ACCOUNT }}}}

      - name: Set up Cloud SDK
        uses: google-github-actions/setup-gcloud@v2

      - name: Deploy to Cloud Run
        run: |
          gcloud run deploy {service_name} \\
            --source . \\
            --region {region} \\
            --allow-unauthenticated
"""

    DOCKER_WORKFLOW = """name: {name}

on:
  push:
    branches: [{branches}]
    tags: ['v*']

env:
  REGISTRY: {registry}
  IMAGE_NAME: ${{{{ github.repository }}}}

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to registry
        uses: docker/login-action@v3
        with:
          registry: ${{{{ env.REGISTRY }}}}
          username: ${{{{ github.actor }}}}
          password: ${{{{ secrets.GITHUB_TOKEN }}}}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{{{ env.REGISTRY }}}}/${{{{ env.IMAGE_NAME }}}}

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{{{ steps.meta.outputs.tags }}}}
          labels: ${{{{ steps.meta.outputs.labels }}}}
          cache-from: type=gha
          cache-to: type=gha,mode=max
"""

    def __init__(self):
        metadata = ToolMetadata(
            name="github_actions_generator",
            description="Generate GitHub Actions workflow files for CI/CD pipelines",
            category="cicd",
            version="1.0.0",
        )
        super().__init__(metadata)

    def _execute(
        self,
        project_path: str = ".",
        workflow_type: str = "auto",  # auto, python, nodejs, docker
        workflow_name: str = "CI/CD Pipeline",
        branches: str = "main",
        include_deploy: bool = True,
        deploy_target: str = "cloud_run",
        service_name: str = "my-service",
        region: str = "us-central1",
        python_version: str = "3.11",
        node_version: str = "20",
        docker_registry: str = "ghcr.io",
        output_file: Optional[str] = None,
    ) -> str:
        """Generate GitHub Actions workflow file"""

        try:
            project = Path(project_path).resolve()

            # Auto-detect project type
            if workflow_type == "auto":
                workflow_type = self._detect_project_type(project)

            # Generate workflow content
            if workflow_type == "python":
                content = self._generate_python_workflow(
                    workflow_name, branches, include_deploy,
                    service_name, region, python_version
                )
            elif workflow_type == "nodejs":
                content = self._generate_nodejs_workflow(
                    workflow_name, branches, include_deploy,
                    service_name, region, node_version
                )
            elif workflow_type == "docker":
                content = self._generate_docker_workflow(
                    workflow_name, branches, docker_registry
                )
            else:
                return GitHubActionsResult(
                    success=False,
                    error=f"Unsupported workflow type: {workflow_type}"
                ).to_json()

            # Write workflow file
            if output_file:
                output_path = Path(output_file)
            else:
                output_path = project / ".github" / "workflows" / "ci.yml"

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content)

            jobs = ["test"]
            if include_deploy:
                jobs.append("deploy")

            return GitHubActionsResult(
                success=True,
                workflow_file=str(output_path),
                workflow_name=workflow_name,
                triggers=["push", "pull_request"],
                jobs=jobs,
                message=f"Generated {workflow_type} workflow at {output_path}"
            ).to_json()

        except Exception as e:
            return GitHubActionsResult(
                success=False,
                error=str(e)
            ).to_json()

    def _detect_project_type(self, project: Path) -> str:
        """Auto-detect project type"""
        if (project / "requirements.txt").exists() or (project / "pyproject.toml").exists():
            return "python"
        elif (project / "package.json").exists():
            return "nodejs"
        elif (project / "Dockerfile").exists():
            return "docker"
        return "python"  # Default

    def _generate_python_workflow(
        self,
        name: str,
        branches: str,
        include_deploy: bool,
        service_name: str,
        region: str,
        python_version: str,
    ) -> str:
        """Generate Python workflow"""
        deploy_job = ""
        if include_deploy:
            deploy_job = self.GCP_DEPLOY_JOB.format(
                service_name=service_name,
                region=region
            )

        return self.PYTHON_WORKFLOW.format(
            name=name,
            branches=branches,
            python_version=python_version,
            deploy_job=deploy_job
        )

    def _generate_nodejs_workflow(
        self,
        name: str,
        branches: str,
        include_deploy: bool,
        service_name: str,
        region: str,
        node_version: str,
    ) -> str:
        """Generate Node.js workflow"""
        deploy_job = ""
        if include_deploy:
            deploy_job = self.GCP_DEPLOY_JOB.format(
                service_name=service_name,
                region=region
            )

        return self.NODEJS_WORKFLOW.format(
            name=name,
            branches=branches,
            node_version=node_version,
            deploy_job=deploy_job
        )

    def _generate_docker_workflow(
        self,
        name: str,
        branches: str,
        registry: str,
    ) -> str:
        """Generate Docker workflow"""
        return self.DOCKER_WORKFLOW.format(
            name=name,
            branches=branches,
            registry=registry
        )


# =============================================================================
# Test Runner Tool
# =============================================================================

class TestRunnerTool(BaseTool):
    """Run tests before deployment with multiple framework support

    Supports:
    - Python: pytest, unittest
    - Node.js: npm test, jest
    - Go: go test
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="test_runner",
            description="Run automated tests before deployment",
            category="cicd",
            version="1.0.0",
        )
        super().__init__(metadata)

    def _execute(
        self,
        project_path: str = ".",
        framework: str = "auto",  # auto, pytest, npm, go
        coverage: bool = True,
        fail_under: float = 0.0,  # Minimum coverage threshold
        timeout: int = 300,
        extra_args: Optional[str] = None,
    ) -> str:
        """Run tests in the project"""

        try:
            project = Path(project_path).resolve()

            # Auto-detect framework
            if framework == "auto":
                framework = self._detect_framework(project)

            # Run tests
            if framework == "pytest":
                return self._run_pytest(project, coverage, fail_under, timeout, extra_args)
            elif framework == "npm":
                return self._run_npm_test(project, timeout, extra_args)
            elif framework == "go":
                return self._run_go_test(project, coverage, timeout, extra_args)
            else:
                return TestRunnerResult(
                    success=False,
                    error=f"Unsupported framework: {framework}"
                ).to_json()

        except Exception as e:
            return TestRunnerResult(
                success=False,
                error=str(e)
            ).to_json()

    def _detect_framework(self, project: Path) -> str:
        """Auto-detect test framework"""
        if (project / "pytest.ini").exists() or (project / "pyproject.toml").exists():
            return "pytest"
        elif (project / "package.json").exists():
            return "npm"
        elif (project / "go.mod").exists():
            return "go"
        elif list(project.glob("**/test_*.py")):
            return "pytest"
        return "pytest"

    def _run_pytest(
        self,
        project: Path,
        coverage: bool,
        fail_under: float,
        timeout: int,
        extra_args: Optional[str],
    ) -> str:
        """Run pytest"""
        pytest_path = shutil.which("pytest")
        if not pytest_path:
            return TestRunnerResult(
                success=False,
                framework="pytest",
                error="pytest not found. Install: pip install pytest"
            ).to_json()

        cmd = [pytest_path, "-v", "--tb=short"]

        if coverage:
            cmd.extend(["--cov=.", "--cov-report=term-missing"])
            if fail_under > 0:
                cmd.append(f"--cov-fail-under={fail_under}")

        if extra_args:
            cmd.extend(extra_args.split())

        import time
        start = time.time()

        result = subprocess.run(
            cmd,
            cwd=project,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        duration = time.time() - start

        # Parse output
        output = result.stdout + result.stderr
        tests_run, passed, failed, skipped = self._parse_pytest_output(output)

        return TestRunnerResult(
            success=result.returncode == 0,
            framework="pytest",
            tests_run=tests_run,
            tests_passed=passed,
            tests_failed=failed,
            tests_skipped=skipped,
            duration=duration,
            output=output[-2000:] if len(output) > 2000 else output,
            message="Tests passed" if result.returncode == 0 else "Tests failed"
        ).to_json()

    def _parse_pytest_output(self, output: str) -> tuple:
        """Parse pytest output for test counts"""
        import re

        # Look for summary line like "5 passed, 1 failed, 2 skipped"
        match = re.search(r"(\d+) passed", output)
        passed = int(match.group(1)) if match else 0

        match = re.search(r"(\d+) failed", output)
        failed = int(match.group(1)) if match else 0

        match = re.search(r"(\d+) skipped", output)
        skipped = int(match.group(1)) if match else 0

        total = passed + failed + skipped
        return total, passed, failed, skipped

    def _run_npm_test(
        self,
        project: Path,
        timeout: int,
        extra_args: Optional[str],
    ) -> str:
        """Run npm test"""
        npm_path = shutil.which("npm")
        if not npm_path:
            return TestRunnerResult(
                success=False,
                framework="npm",
                error="npm not found"
            ).to_json()

        cmd = [npm_path, "test"]
        if extra_args:
            cmd.extend(["--", extra_args])

        import time
        start = time.time()

        result = subprocess.run(
            cmd,
            cwd=project,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        duration = time.time() - start
        output = result.stdout + result.stderr

        return TestRunnerResult(
            success=result.returncode == 0,
            framework="npm",
            duration=duration,
            output=output[-2000:] if len(output) > 2000 else output,
            message="Tests passed" if result.returncode == 0 else "Tests failed"
        ).to_json()

    def _run_go_test(
        self,
        project: Path,
        coverage: bool,
        timeout: int,
        extra_args: Optional[str],
    ) -> str:
        """Run go test"""
        go_path = shutil.which("go")
        if not go_path:
            return TestRunnerResult(
                success=False,
                framework="go",
                error="go not found"
            ).to_json()

        cmd = [go_path, "test", "-v", "./..."]
        if coverage:
            cmd.append("-cover")

        if extra_args:
            cmd.extend(extra_args.split())

        import time
        start = time.time()

        result = subprocess.run(
            cmd,
            cwd=project,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        duration = time.time() - start
        output = result.stdout + result.stderr

        return TestRunnerResult(
            success=result.returncode == 0,
            framework="go",
            duration=duration,
            output=output[-2000:] if len(output) > 2000 else output,
            message="Tests passed" if result.returncode == 0 else "Tests failed"
        ).to_json()


# =============================================================================
# CloudBuild YAML Generator Tool
# =============================================================================

class CloudBuildConfigGeneratorTool(BaseTool):
    """Generate cloudbuild.yaml configuration files

    Creates optimized Cloud Build configs for:
    - Python applications
    - Node.js applications
    - Docker builds
    - Multi-stage builds with caching
    """

    PYTHON_CONFIG = """steps:
  # Install dependencies
  - name: 'python:{python_version}'
    entrypoint: pip
    args: ['install', '-r', 'requirements.txt', '--user']

  # Run tests
  - name: 'python:{python_version}'
    entrypoint: python
    args: ['-m', 'pytest', '-v']

  # Build container
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'build'
      - '-t'
      - '{region}-docker.pkg.dev/$PROJECT_ID/{repo}/{service}:$COMMIT_SHA'
      - '-t'
      - '{region}-docker.pkg.dev/$PROJECT_ID/{repo}/{service}:latest'
      - '.'

  # Push container
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'push'
      - '{region}-docker.pkg.dev/$PROJECT_ID/{repo}/{service}:$COMMIT_SHA'

  # Deploy to Cloud Run
  - name: 'gcr.io/cloud-builders/gcloud'
    args:
      - 'run'
      - 'deploy'
      - '{service}'
      - '--image'
      - '{region}-docker.pkg.dev/$PROJECT_ID/{repo}/{service}:$COMMIT_SHA'
      - '--region'
      - '{region}'
      - '--platform'
      - 'managed'
      - '--allow-unauthenticated'

images:
  - '{region}-docker.pkg.dev/$PROJECT_ID/{repo}/{service}:$COMMIT_SHA'
  - '{region}-docker.pkg.dev/$PROJECT_ID/{repo}/{service}:latest'

options:
  logging: CLOUD_LOGGING_ONLY
  machineType: 'E2_HIGHCPU_8'

timeout: '1200s'

substitutions:
  _DEPLOY_REGION: '{region}'
  _SERVICE_NAME: '{service}'
"""

    NODEJS_CONFIG = """steps:
  # Install dependencies
  - name: 'node:{node_version}'
    entrypoint: npm
    args: ['ci']

  # Run linter
  - name: 'node:{node_version}'
    entrypoint: npm
    args: ['run', 'lint', '--if-present']

  # Run tests
  - name: 'node:{node_version}'
    entrypoint: npm
    args: ['test', '--', '--passWithNoTests']

  # Build container
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'build'
      - '-t'
      - '{region}-docker.pkg.dev/$PROJECT_ID/{repo}/{service}:$COMMIT_SHA'
      - '.'

  # Push and deploy
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', '{region}-docker.pkg.dev/$PROJECT_ID/{repo}/{service}:$COMMIT_SHA']

  - name: 'gcr.io/cloud-builders/gcloud'
    args:
      - 'run'
      - 'deploy'
      - '{service}'
      - '--image'
      - '{region}-docker.pkg.dev/$PROJECT_ID/{repo}/{service}:$COMMIT_SHA'
      - '--region'
      - '{region}'
      - '--platform'
      - 'managed'

images:
  - '{region}-docker.pkg.dev/$PROJECT_ID/{repo}/{service}:$COMMIT_SHA'

options:
  logging: CLOUD_LOGGING_ONLY

timeout: '900s'
"""

    def __init__(self):
        metadata = ToolMetadata(
            name="cloudbuild_config_generator",
            description="Generate cloudbuild.yaml configuration files",
            category="cicd",
            version="1.0.0",
        )
        super().__init__(metadata)

    def _execute(
        self,
        project_path: str = ".",
        project_type: str = "auto",
        service_name: str = "my-service",
        region: str = "us-central1",
        repo_name: str = "cloud-run-source-deploy",
        python_version: str = "3.11",
        node_version: str = "20",
        output_file: Optional[str] = None,
    ) -> str:
        """Generate cloudbuild.yaml"""

        try:
            project = Path(project_path).resolve()

            # Auto-detect
            if project_type == "auto":
                if (project / "requirements.txt").exists():
                    project_type = "python"
                elif (project / "package.json").exists():
                    project_type = "nodejs"
                else:
                    project_type = "python"

            # Generate config
            if project_type == "python":
                content = self.PYTHON_CONFIG.format(
                    python_version=python_version,
                    service=service_name,
                    region=region,
                    repo=repo_name,
                )
            elif project_type == "nodejs":
                content = self.NODEJS_CONFIG.format(
                    node_version=node_version,
                    service=service_name,
                    region=region,
                    repo=repo_name,
                )
            else:
                return json.dumps({
                    "success": False,
                    "error": f"Unsupported project type: {project_type}"
                })

            # Write file
            output_path = Path(output_file) if output_file else project / "cloudbuild.yaml"
            output_path.write_text(content)

            return json.dumps({
                "success": True,
                "config_file": str(output_path),
                "project_type": project_type,
                "service_name": service_name,
                "region": region,
                "message": f"Generated cloudbuild.yaml at {output_path}"
            }, indent=2)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e)
            })
