"""Code analysis tools - tech stack detection, dependency scanning"""

import json
import subprocess
import shutil
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

class TechStackResult(BaseModel):
    """Result of tech stack analysis"""
    success: bool
    project_path: str
    language: Optional[str] = None
    languages: List[str] = Field(default_factory=list)
    framework: Optional[str] = None
    frameworks: List[str] = Field(default_factory=list)
    runtime: Optional[str] = None
    package_manager: Optional[str] = None
    dependencies_count: int = 0
    suggested_cloud_services: List[str] = Field(default_factory=list)
    detected_files: Dict[str, bool] = Field(default_factory=dict)
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class DependencyScanResult(BaseModel):
    """Result of dependency vulnerability scan"""
    success: bool
    project_path: str
    scanner_used: Optional[str] = None
    total_dependencies: int = 0
    vulnerabilities_found: int = 0
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    vulnerabilities: List[Dict[str, Any]] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# File Pattern Definitions
# =============================================================================

# Language detection patterns
LANGUAGE_PATTERNS = {
    "python": {
        "files": ["requirements.txt", "pyproject.toml", "setup.py", "Pipfile", "poetry.lock"],
        "extensions": [".py"],
        "runtime": "python",
        "package_manager": "pip"
    },
    "javascript": {
        "files": ["package.json", "yarn.lock", "pnpm-lock.yaml"],
        "extensions": [".js", ".jsx"],
        "runtime": "node",
        "package_manager": "npm"
    },
    "typescript": {
        "files": ["tsconfig.json", "package.json"],
        "extensions": [".ts", ".tsx"],
        "runtime": "node",
        "package_manager": "npm"
    },
    "go": {
        "files": ["go.mod", "go.sum"],
        "extensions": [".go"],
        "runtime": "go",
        "package_manager": "go mod"
    },
    "rust": {
        "files": ["Cargo.toml", "Cargo.lock"],
        "extensions": [".rs"],
        "runtime": "rust",
        "package_manager": "cargo"
    },
    "java": {
        "files": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "extensions": [".java"],
        "runtime": "jvm",
        "package_manager": "maven/gradle"
    },
    "csharp": {
        "files": ["*.csproj", "*.sln", "nuget.config"],
        "extensions": [".cs"],
        "runtime": "dotnet",
        "package_manager": "nuget"
    },
    "ruby": {
        "files": ["Gemfile", "Gemfile.lock"],
        "extensions": [".rb"],
        "runtime": "ruby",
        "package_manager": "bundler"
    },
    "php": {
        "files": ["composer.json", "composer.lock"],
        "extensions": [".php"],
        "runtime": "php",
        "package_manager": "composer"
    }
}

# Framework detection patterns
FRAMEWORK_PATTERNS = {
    # Python frameworks
    "fastapi": {"indicators": ["fastapi", "uvicorn"], "language": "python", "type": "web"},
    "django": {"indicators": ["django"], "language": "python", "type": "web"},
    "flask": {"indicators": ["flask"], "language": "python", "type": "web"},
    "streamlit": {"indicators": ["streamlit"], "language": "python", "type": "web"},
    "pytorch": {"indicators": ["torch", "pytorch"], "language": "python", "type": "ml"},
    "tensorflow": {"indicators": ["tensorflow", "keras"], "language": "python", "type": "ml"},

    # JavaScript/TypeScript frameworks
    "react": {"indicators": ["react", "react-dom"], "language": "javascript", "type": "frontend"},
    "nextjs": {"indicators": ["next"], "language": "javascript", "type": "fullstack"},
    "vue": {"indicators": ["vue"], "language": "javascript", "type": "frontend"},
    "angular": {"indicators": ["@angular/core"], "language": "typescript", "type": "frontend"},
    "express": {"indicators": ["express"], "language": "javascript", "type": "backend"},
    "nestjs": {"indicators": ["@nestjs/core"], "language": "typescript", "type": "backend"},

    # Go frameworks
    "gin": {"indicators": ["github.com/gin-gonic/gin"], "language": "go", "type": "web"},
    "fiber": {"indicators": ["github.com/gofiber/fiber"], "language": "go", "type": "web"},

    # Java frameworks
    "spring": {"indicators": ["spring-boot", "spring-framework"], "language": "java", "type": "web"},
}

# Cloud service suggestions based on detected tech
CLOUD_SERVICE_SUGGESTIONS = {
    "web": ["Cloud Run", "App Engine", "Cloud Functions"],
    "frontend": ["Cloud Storage + CDN", "Firebase Hosting"],
    "backend": ["Cloud Run", "GKE", "Compute Engine"],
    "ml": ["Vertex AI", "AI Platform", "Cloud Functions + GPU"],
    "fullstack": ["Cloud Run", "App Engine", "GKE"],
    "database": {
        "postgres": ["Cloud SQL (PostgreSQL)"],
        "mysql": ["Cloud SQL (MySQL)"],
        "mongodb": ["MongoDB Atlas on GCP"],
        "redis": ["Memorystore (Redis)"],
        "firestore": ["Firestore"],
    }
}


# =============================================================================
# Tech Stack Analyzer Tool
# =============================================================================

class TechStackAnalyzerTool(BaseTool):
    """Analyze project directory to detect tech stack

    Features:
    - Detect primary language and frameworks
    - Identify runtime and package manager
    - Count dependencies
    - Suggest appropriate cloud services
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="tech_stack_analyzer",
                description="Analyze project to detect language, framework, and suggest cloud services",
                category="code-analysis",
                tags=["analysis", "deployment", "devops", "tech-stack"]
            )
        )

    def _detect_languages(self, project_path: Path) -> List[Dict[str, Any]]:
        """Detect programming languages used"""
        detected = []

        for lang, patterns in LANGUAGE_PATTERNS.items():
            score = 0
            detected_files = []

            # Check for config files
            for file_pattern in patterns["files"]:
                if "*" in file_pattern:
                    matches = list(project_path.glob(file_pattern))
                    if matches:
                        score += 2
                        detected_files.extend([m.name for m in matches])
                elif (project_path / file_pattern).exists():
                    score += 2
                    detected_files.append(file_pattern)

            # Check for source files (sample check, not full scan)
            for ext in patterns["extensions"]:
                src_files = list(project_path.rglob(f"*{ext}"))[:100]  # Limit scan
                if src_files:
                    score += min(len(src_files), 10)

            if score > 0:
                detected.append({
                    "language": lang,
                    "score": score,
                    "runtime": patterns["runtime"],
                    "package_manager": patterns["package_manager"],
                    "detected_files": detected_files
                })

        # Sort by score
        detected.sort(key=lambda x: x["score"], reverse=True)
        return detected

    def _detect_frameworks(self, project_path: Path, primary_language: str) -> List[str]:
        """Detect frameworks based on dependency files"""
        frameworks = []

        # Read dependency files based on language
        deps_content = ""

        if primary_language == "python":
            for dep_file in ["requirements.txt", "pyproject.toml", "Pipfile"]:
                dep_path = project_path / dep_file
                if dep_path.exists():
                    deps_content += dep_path.read_text(encoding="utf-8", errors="ignore")

        elif primary_language in ["javascript", "typescript"]:
            pkg_json = project_path / "package.json"
            if pkg_json.exists():
                deps_content = pkg_json.read_text(encoding="utf-8", errors="ignore")

        elif primary_language == "go":
            go_mod = project_path / "go.mod"
            if go_mod.exists():
                deps_content = go_mod.read_text(encoding="utf-8", errors="ignore")

        elif primary_language == "java":
            for dep_file in ["pom.xml", "build.gradle"]:
                dep_path = project_path / dep_file
                if dep_path.exists():
                    deps_content += dep_path.read_text(encoding="utf-8", errors="ignore")

        # Check for framework indicators
        deps_lower = deps_content.lower()
        for framework, info in FRAMEWORK_PATTERNS.items():
            if info["language"] == primary_language or info["language"] in ["javascript", "typescript"] and primary_language in ["javascript", "typescript"]:
                for indicator in info["indicators"]:
                    if indicator.lower() in deps_lower:
                        frameworks.append(framework)
                        break

        return frameworks

    def _count_dependencies(self, project_path: Path, language: str) -> int:
        """Count number of dependencies"""
        try:
            if language == "python":
                req_file = project_path / "requirements.txt"
                if req_file.exists():
                    lines = req_file.read_text(encoding="utf-8", errors="ignore").strip().split("\n")
                    return len([l for l in lines if l.strip() and not l.strip().startswith("#")])

            elif language in ["javascript", "typescript"]:
                pkg_json = project_path / "package.json"
                if pkg_json.exists():
                    data = json.loads(pkg_json.read_text(encoding="utf-8"))
                    deps = data.get("dependencies", {})
                    dev_deps = data.get("devDependencies", {})
                    return len(deps) + len(dev_deps)

            elif language == "go":
                go_mod = project_path / "go.mod"
                if go_mod.exists():
                    content = go_mod.read_text(encoding="utf-8", errors="ignore")
                    # Count require statements
                    return content.count("\n\t") + content.count("require ")

        except Exception as e:
            logger.warning(f"Failed to count dependencies: {e}")

        return 0

    def _suggest_cloud_services(self, frameworks: List[str], language: str) -> List[str]:
        """Suggest cloud services based on detected stack"""
        suggestions = set()

        for framework in frameworks:
            if framework in FRAMEWORK_PATTERNS:
                fw_type = FRAMEWORK_PATTERNS[framework]["type"]
                if fw_type in CLOUD_SERVICE_SUGGESTIONS:
                    suggestions.update(CLOUD_SERVICE_SUGGESTIONS[fw_type])

        # Default suggestions if no specific framework
        if not suggestions:
            suggestions.add("Cloud Run")
            suggestions.add("Cloud Build")

        # Always suggest these
        suggestions.add("Cloud Build")
        suggestions.add("Secret Manager")
        suggestions.add("Cloud Logging")

        return sorted(list(suggestions))

    def _execute(self, project_path: str = ".") -> str:
        """Analyze project tech stack

        Args:
            project_path: Path to project directory

        Returns:
            JSON with tech stack analysis
        """
        try:
            path = Path(project_path).resolve()

            if not path.exists():
                return TechStackResult(
                    success=False,
                    project_path=str(path),
                    error=f"Project path does not exist: {path}",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

            if not path.is_dir():
                return TechStackResult(
                    success=False,
                    project_path=str(path),
                    error="Path is not a directory",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

            # Detect languages
            languages = self._detect_languages(path)

            if not languages:
                return TechStackResult(
                    success=True,
                    project_path=str(path),
                    error="No recognized programming language detected",
                    detected_files={}
                ).to_json()

            primary = languages[0]
            primary_lang = primary["language"]

            # Detect frameworks
            frameworks = self._detect_frameworks(path, primary_lang)

            # Count dependencies
            deps_count = self._count_dependencies(path, primary_lang)

            # Suggest cloud services
            suggestions = self._suggest_cloud_services(frameworks, primary_lang)

            # Build detected files dict
            detected_files = {}
            for lang_info in languages:
                for f in lang_info.get("detected_files", []):
                    detected_files[f] = True

            logger.info(f"Tech stack analyzed: {primary_lang}", extra={
                "language": primary_lang,
                "frameworks": frameworks,
                "dependencies": deps_count
            })

            return TechStackResult(
                success=True,
                project_path=str(path),
                language=primary_lang,
                languages=[l["language"] for l in languages],
                framework=frameworks[0] if frameworks else None,
                frameworks=frameworks,
                runtime=primary["runtime"],
                package_manager=primary["package_manager"],
                dependencies_count=deps_count,
                suggested_cloud_services=suggestions,
                detected_files=detected_files
            ).to_json()

        except Exception as e:
            logger.error(f"Tech stack analysis failed: {e}", exc_info=True)
            return TechStackResult(
                success=False,
                project_path=project_path,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


# =============================================================================
# Dependency Scanner Tool
# =============================================================================

class DependencyScannerTool(BaseTool):
    """Scan dependencies for vulnerabilities

    Features:
    - Supports Python (pip-audit/safety), Node (npm audit), Go (govulncheck)
    - Returns vulnerability counts by severity
    - Provides remediation recommendations
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="dependency_scanner",
                description="Scan project dependencies for security vulnerabilities",
                category="code-analysis",
                tags=["security", "vulnerabilities", "dependencies", "devops"]
            )
        )

    def _run_command(self, cmd: List[str], cwd: str, timeout: int = 120) -> subprocess.CompletedProcess:
        """Run shell command"""
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout
        )

    def _scan_python(self, project_path: Path) -> Dict[str, Any]:
        """Scan Python dependencies using pip-audit or safety"""
        result = {
            "scanner": None,
            "vulnerabilities": [],
            "total": 0,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0
        }

        # Try pip-audit first
        pip_audit = shutil.which("pip-audit")
        if pip_audit:
            try:
                req_file = project_path / "requirements.txt"
                if req_file.exists():
                    cmd = [pip_audit, "-r", str(req_file), "--format", "json"]
                else:
                    cmd = [pip_audit, "--format", "json"]

                proc = self._run_command(cmd, str(project_path))

                if proc.stdout:
                    result["scanner"] = "pip-audit"
                    try:
                        vulns = json.loads(proc.stdout)
                        result["vulnerabilities"] = vulns if isinstance(vulns, list) else []
                        result["total"] = len(result["vulnerabilities"])
                    except json.JSONDecodeError:
                        pass
                return result

            except subprocess.TimeoutExpired:
                logger.warning("pip-audit timed out")

        # Try safety as fallback
        safety = shutil.which("safety")
        if safety:
            try:
                req_file = project_path / "requirements.txt"
                if req_file.exists():
                    cmd = [safety, "check", "-r", str(req_file), "--json"]
                    proc = self._run_command(cmd, str(project_path))

                    if proc.stdout:
                        result["scanner"] = "safety"
                        try:
                            data = json.loads(proc.stdout)
                            vulns = data.get("vulnerabilities", [])
                            result["vulnerabilities"] = vulns
                            result["total"] = len(vulns)
                        except json.JSONDecodeError:
                            pass
                return result

            except subprocess.TimeoutExpired:
                logger.warning("safety check timed out")

        return result

    def _scan_node(self, project_path: Path) -> Dict[str, Any]:
        """Scan Node.js dependencies using npm audit"""
        result = {
            "scanner": "npm audit",
            "vulnerabilities": [],
            "total": 0,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0
        }

        npm = shutil.which("npm")
        if not npm:
            return result

        try:
            # Check if package-lock.json exists
            if not (project_path / "package-lock.json").exists():
                # Run npm install first to generate lock file
                self._run_command([npm, "install", "--package-lock-only"], str(project_path), timeout=180)

            cmd = [npm, "audit", "--json"]
            proc = self._run_command(cmd, str(project_path))

            if proc.stdout:
                try:
                    data = json.loads(proc.stdout)
                    vulns = data.get("vulnerabilities", {})

                    if isinstance(vulns, dict):
                        result["total"] = len(vulns)
                        for name, info in vulns.items():
                            severity = info.get("severity", "low").lower()
                            if severity == "critical":
                                result["critical"] += 1
                            elif severity == "high":
                                result["high"] += 1
                            elif severity == "moderate" or severity == "medium":
                                result["medium"] += 1
                            else:
                                result["low"] += 1

                            result["vulnerabilities"].append({
                                "package": name,
                                "severity": severity,
                                "via": info.get("via", []),
                                "fixAvailable": info.get("fixAvailable", False)
                            })

                except json.JSONDecodeError:
                    pass

        except subprocess.TimeoutExpired:
            logger.warning("npm audit timed out")

        return result

    def _scan_go(self, project_path: Path) -> Dict[str, Any]:
        """Scan Go dependencies using govulncheck"""
        result = {
            "scanner": None,
            "vulnerabilities": [],
            "total": 0,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0
        }

        govulncheck = shutil.which("govulncheck")
        if not govulncheck:
            return result

        try:
            cmd = [govulncheck, "-json", "./..."]
            proc = self._run_command(cmd, str(project_path), timeout=180)

            if proc.stdout:
                result["scanner"] = "govulncheck"
                # govulncheck outputs JSON lines
                for line in proc.stdout.strip().split("\n"):
                    if line:
                        try:
                            data = json.loads(line)
                            if "vulnerability" in data:
                                result["vulnerabilities"].append(data["vulnerability"])
                                result["total"] += 1
                        except json.JSONDecodeError:
                            continue

        except subprocess.TimeoutExpired:
            logger.warning("govulncheck timed out")

        return result

    def _execute(self, project_path: str = ".") -> str:
        """Scan dependencies for vulnerabilities

        Args:
            project_path: Path to project directory

        Returns:
            JSON with vulnerability scan results
        """
        try:
            path = Path(project_path).resolve()

            if not path.exists() or not path.is_dir():
                return DependencyScanResult(
                    success=False,
                    project_path=str(path),
                    error="Invalid project path",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

            # Detect language first
            scan_result = None
            scanner_used = None

            # Check for Python
            if (path / "requirements.txt").exists() or (path / "pyproject.toml").exists():
                scan_result = self._scan_python(path)
                scanner_used = scan_result.get("scanner")

            # Check for Node.js
            elif (path / "package.json").exists():
                scan_result = self._scan_node(path)
                scanner_used = "npm audit"

            # Check for Go
            elif (path / "go.mod").exists():
                scan_result = self._scan_go(path)
                scanner_used = scan_result.get("scanner")

            if not scan_result or not scanner_used:
                return DependencyScanResult(
                    success=False,
                    project_path=str(path),
                    error="No supported package manager found or scanner not installed",
                    recommendations=[
                        "Install pip-audit: pip install pip-audit",
                        "Install safety: pip install safety",
                        "For Node.js: npm is required",
                        "For Go: install govulncheck"
                    ],
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                ).to_json()

            # Build recommendations
            recommendations = []
            if scan_result["critical"] > 0:
                recommendations.append("CRITICAL: Immediately update packages with critical vulnerabilities")
            if scan_result["high"] > 0:
                recommendations.append("HIGH: Update packages with high severity vulnerabilities as soon as possible")
            if scan_result["total"] == 0:
                recommendations.append("No known vulnerabilities found")
            else:
                recommendations.append(f"Run '{scanner_used}' locally for detailed fix suggestions")

            logger.info(f"Dependency scan complete: {scan_result['total']} vulnerabilities", extra={
                "scanner": scanner_used,
                "total": scan_result["total"],
                "critical": scan_result["critical"]
            })

            return DependencyScanResult(
                success=True,
                project_path=str(path),
                scanner_used=scanner_used,
                total_dependencies=0,  # Would need separate count
                vulnerabilities_found=scan_result["total"],
                critical=scan_result["critical"],
                high=scan_result["high"],
                medium=scan_result["medium"],
                low=scan_result["low"],
                vulnerabilities=scan_result["vulnerabilities"][:20],  # Limit output
                recommendations=recommendations
            ).to_json()

        except Exception as e:
            logger.error(f"Dependency scan failed: {e}", exc_info=True)
            return DependencyScanResult(
                success=False,
                project_path=project_path,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


# =============================================================================
# Dockerfile Analyzer Tool
# =============================================================================

class DockerfileAnalyzerTool(BaseTool):
    """Analyze Dockerfile for deployment configuration

    Features:
    - Extract base image
    - Detect exposed ports
    - Identify entry point
    - Suggest optimizations
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="dockerfile_analyzer",
                description="Analyze Dockerfile to extract deployment configuration",
                category="code-analysis",
                tags=["docker", "containers", "deployment", "devops"]
            )
        )

    def _execute(self, project_path: str = ".", dockerfile: str = "Dockerfile") -> str:
        """Analyze Dockerfile

        Args:
            project_path: Path to project directory
            dockerfile: Dockerfile name (default: Dockerfile)

        Returns:
            JSON with Dockerfile analysis
        """
        try:
            path = Path(project_path).resolve()
            dockerfile_path = path / dockerfile

            if not dockerfile_path.exists():
                return json.dumps({
                    "success": False,
                    "error": f"Dockerfile not found: {dockerfile_path}",
                    "exists": False
                }, indent=2)

            content = dockerfile_path.read_text(encoding="utf-8")
            lines = content.strip().split("\n")

            result = {
                "success": True,
                "exists": True,
                "path": str(dockerfile_path),
                "base_image": None,
                "exposed_ports": [],
                "workdir": None,
                "entrypoint": None,
                "cmd": None,
                "env_vars": [],
                "stages": [],
                "optimizations": []
            }

            current_stage = "default"

            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                upper_line = line.upper()

                if upper_line.startswith("FROM "):
                    image = line[5:].strip().split(" AS ")[0].strip()
                    if " AS " in line.upper():
                        current_stage = line.upper().split(" AS ")[1].strip()
                        result["stages"].append(current_stage)
                    if not result["base_image"]:
                        result["base_image"] = image

                elif upper_line.startswith("EXPOSE "):
                    ports = line[7:].strip().split()
                    result["exposed_ports"].extend(ports)

                elif upper_line.startswith("WORKDIR "):
                    result["workdir"] = line[8:].strip()

                elif upper_line.startswith("ENTRYPOINT "):
                    result["entrypoint"] = line[11:].strip()

                elif upper_line.startswith("CMD "):
                    result["cmd"] = line[4:].strip()

                elif upper_line.startswith("ENV "):
                    env_parts = line[4:].strip().split("=", 1)
                    if len(env_parts) == 2:
                        result["env_vars"].append(env_parts[0].strip())

            # Suggest optimizations
            if result["base_image"]:
                if ":latest" in result["base_image"]:
                    result["optimizations"].append("Use specific version tags instead of :latest")
                if not any(slim in result["base_image"] for slim in ["slim", "alpine", "distroless"]):
                    result["optimizations"].append("Consider using slim/alpine base image to reduce size")

            if not result["stages"]:
                result["optimizations"].append("Consider multi-stage builds to reduce final image size")

            logger.info(f"Dockerfile analyzed: {dockerfile_path}")

            return json.dumps(result, indent=2)

        except Exception as e:
            logger.error(f"Dockerfile analysis failed: {e}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": f"{type(e).__name__}: {str(e)}"
            }, indent=2)


# =============================================================================
# Dockerfile Generator Tool (CRITICAL for end-to-end automation)
# =============================================================================

# Dockerfile templates by framework
DOCKERFILE_TEMPLATES = {
    "python": {
        "default": """# Auto-generated Dockerfile for Python application
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Cloud Run requires listening on PORT environment variable
EXPOSE $PORT

# Default command (override as needed)
CMD ["python", "main.py"]
""",
        "fastapi": """# Auto-generated Dockerfile for FastAPI application
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

EXPOSE $PORT

# FastAPI with uvicorn - listens on PORT from environment
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]
""",
        "flask": """# Auto-generated Dockerfile for Flask application
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV FLASK_APP=app.py

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE $PORT

# Flask with gunicorn for production
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT app:app"]
""",
        "django": """# Auto-generated Dockerfile for Django application
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Collect static files
RUN python manage.py collectstatic --noinput

EXPOSE $PORT

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT config.wsgi:application"]
""",
        "streamlit": """# Auto-generated Dockerfile for Streamlit application
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE $PORT

CMD ["sh", "-c", "streamlit run app.py --server.port=$PORT --server.address=0.0.0.0"]
"""
    },
    "javascript": {
        "default": """# Auto-generated Dockerfile for Node.js application
FROM node:20-alpine

ENV NODE_ENV=production
ENV PORT=8080

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm ci --only=production

# Copy application code
COPY . .

EXPOSE $PORT

CMD ["node", "index.js"]
""",
        "express": """# Auto-generated Dockerfile for Express.js application
FROM node:20-alpine

ENV NODE_ENV=production
ENV PORT=8080

WORKDIR /app

COPY package*.json ./
RUN npm ci --only=production

COPY . .

EXPOSE $PORT

CMD ["node", "server.js"]
""",
        "nextjs": """# Auto-generated Dockerfile for Next.js application
FROM node:20-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
ENV NODE_ENV=production
ENV PORT=8080

WORKDIR /app
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE $PORT
CMD ["node", "server.js"]
"""
    },
    "typescript": {
        "default": """# Auto-generated Dockerfile for TypeScript application
FROM node:20-alpine AS builder

WORKDIR /app
COPY package*.json tsconfig*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine
ENV NODE_ENV=production
ENV PORT=8080

WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/package*.json ./
RUN npm ci --only=production

EXPOSE $PORT
CMD ["node", "dist/index.js"]
""",
        "nestjs": """# Auto-generated Dockerfile for NestJS application
FROM node:20-alpine AS builder

WORKDIR /app
COPY package*.json tsconfig*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine
ENV NODE_ENV=production
ENV PORT=8080

WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/package*.json ./
RUN npm ci --only=production

EXPOSE $PORT
CMD ["node", "dist/main.js"]
"""
    },
    "go": {
        "default": """# Auto-generated Dockerfile for Go application
FROM golang:1.21-alpine AS builder

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o main .

FROM alpine:latest
ENV PORT=8080

WORKDIR /app
COPY --from=builder /app/main .

EXPOSE $PORT
CMD ["./main"]
""",
        "gin": """# Auto-generated Dockerfile for Gin application
FROM golang:1.21-alpine AS builder

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o server .

FROM alpine:latest
ENV PORT=8080
ENV GIN_MODE=release

WORKDIR /app
COPY --from=builder /app/server .

EXPOSE $PORT
CMD ["./server"]
"""
    },
    "java": {
        "default": """# Auto-generated Dockerfile for Java application
FROM eclipse-temurin:17-jdk-alpine AS builder

WORKDIR /app
COPY . .
RUN ./mvnw clean package -DskipTests

FROM eclipse-temurin:17-jre-alpine
ENV PORT=8080

WORKDIR /app
COPY --from=builder /app/target/*.jar app.jar

EXPOSE $PORT
CMD ["sh", "-c", "java -jar app.jar --server.port=$PORT"]
""",
        "spring": """# Auto-generated Dockerfile for Spring Boot application
FROM eclipse-temurin:17-jdk-alpine AS builder

WORKDIR /app
COPY . .
RUN ./mvnw clean package -DskipTests

FROM eclipse-temurin:17-jre-alpine
ENV PORT=8080

WORKDIR /app
COPY --from=builder /app/target/*.jar app.jar

EXPOSE $PORT
CMD ["sh", "-c", "java -Dserver.port=$PORT -jar app.jar"]
"""
    },
    "rust": {
        "default": """# Auto-generated Dockerfile for Rust application
FROM rust:1.75-alpine AS builder

RUN apk add --no-cache musl-dev
WORKDIR /app
COPY . .
RUN cargo build --release

FROM alpine:latest
ENV PORT=8080

WORKDIR /app
COPY --from=builder /app/target/release/app .

EXPOSE $PORT
CMD ["./app"]
"""
    },
    "ruby": {
        "default": """# Auto-generated Dockerfile for Ruby application
FROM ruby:3.2-slim

ENV PORT=8080
ENV RAILS_ENV=production

WORKDIR /app

COPY Gemfile Gemfile.lock ./
RUN bundle install --without development test

COPY . .

EXPOSE $PORT
CMD ["sh", "-c", "bundle exec rails server -b 0.0.0.0 -p $PORT"]
"""
    }
}


class DockerfileGeneratorResult(BaseModel):
    """Result of Dockerfile generation"""
    success: bool
    project_path: str
    dockerfile_path: Optional[str] = None
    dockerfile_content: Optional[str] = None
    language: Optional[str] = None
    framework: Optional[str] = None
    entrypoint_detected: Optional[str] = None
    port: int = 8080
    already_exists: bool = False
    overwritten: bool = False
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class DockerfileGeneratorTool(BaseTool):
    """Generate Dockerfile based on detected tech stack

    CRITICAL for end-to-end deployment automation.
    Generates optimized, Cloud Run-compatible Dockerfiles.

    Features:
    - Auto-detect language and framework
    - Generate appropriate Dockerfile
    - Configure PORT environment variable (Cloud Run requirement)
    - Multi-stage builds for production
    - Health check configuration
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="dockerfile_generator",
                description="Generate Dockerfile based on detected tech stack for Cloud Run deployment",
                category="code-analysis",
                tags=["docker", "containers", "deployment", "devops", "generator"]
            )
        )

    def _detect_entrypoint(self, project_path: Path, language: str, framework: Optional[str]) -> Optional[str]:
        """Detect the main entry point file"""
        # Python entry points
        if language == "python":
            for candidate in ["main.py", "app.py", "server.py", "run.py", "wsgi.py", "asgi.py"]:
                if (project_path / candidate).exists():
                    return candidate
            # Check for package with __main__.py
            for subdir in project_path.iterdir():
                if subdir.is_dir() and (subdir / "__main__.py").exists():
                    return f"{subdir.name}/__main__.py"

        # Node.js entry points
        elif language in ["javascript", "typescript"]:
            pkg_json = project_path / "package.json"
            if pkg_json.exists():
                try:
                    data = json.loads(pkg_json.read_text())
                    if "main" in data:
                        return data["main"]
                    if "scripts" in data and "start" in data["scripts"]:
                        return "package.json scripts.start"
                except:
                    pass
            for candidate in ["index.js", "server.js", "app.js", "main.js", "index.ts", "server.ts"]:
                if (project_path / candidate).exists():
                    return candidate

        # Go entry points
        elif language == "go":
            for candidate in ["main.go", "cmd/main.go", "cmd/server/main.go"]:
                if (project_path / candidate).exists():
                    return candidate

        return None

    def _customize_template(self, template: str, project_path: Path, language: str, framework: Optional[str], entrypoint: Optional[str]) -> str:
        """Customize Dockerfile template based on project specifics"""
        dockerfile = template

        # Customize entrypoint for Python
        if language == "python" and entrypoint:
            if framework == "fastapi":
                # Extract module name from entrypoint
                module = entrypoint.replace(".py", "").replace("/", ".")
                dockerfile = dockerfile.replace(
                    'CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]',
                    f'CMD ["sh", "-c", "uvicorn {module}:app --host 0.0.0.0 --port $PORT"]'
                )
            elif framework == "flask":
                module = entrypoint.replace(".py", "")
                dockerfile = dockerfile.replace(
                    'CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT app:app"]',
                    f'CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT {module}:app"]'
                )
            elif not framework or framework == "default":
                dockerfile = dockerfile.replace(
                    'CMD ["python", "main.py"]',
                    f'CMD ["python", "{entrypoint}"]'
                )

        # Customize for Node.js
        elif language in ["javascript", "typescript"] and entrypoint:
            if entrypoint.endswith(".js"):
                dockerfile = dockerfile.replace(
                    'CMD ["node", "index.js"]',
                    f'CMD ["node", "{entrypoint}"]'
                )
                dockerfile = dockerfile.replace(
                    'CMD ["node", "server.js"]',
                    f'CMD ["node", "{entrypoint}"]'
                )

        return dockerfile

    def _execute(
        self,
        project_path: str = ".",
        force: bool = False,
        language: Optional[str] = None,
        framework: Optional[str] = None,
        port: int = 8080
    ) -> str:
        """Generate Dockerfile for the project

        Args:
            project_path: Path to project directory
            force: Overwrite existing Dockerfile
            language: Override language detection
            framework: Override framework detection
            port: Port to expose (default 8080 for Cloud Run)

        Returns:
            JSON with generation result
        """
        try:
            path = Path(project_path).resolve()
            dockerfile_path = path / "Dockerfile"
            warnings = []

            if not path.exists() or not path.is_dir():
                return DockerfileGeneratorResult(
                    success=False,
                    project_path=str(path),
                    error="Invalid project path"
                ).to_json()

            # Check if Dockerfile already exists
            if dockerfile_path.exists() and not force:
                return DockerfileGeneratorResult(
                    success=False,
                    project_path=str(path),
                    already_exists=True,
                    error="Dockerfile already exists. Use force=true to overwrite."
                ).to_json()

            # Detect language if not provided
            if not language:
                analyzer = TechStackAnalyzerTool()
                analysis = json.loads(analyzer._execute(project_path))
                if not analysis.get("success") or not analysis.get("language"):
                    return DockerfileGeneratorResult(
                        success=False,
                        project_path=str(path),
                        error="Could not detect project language. Please specify language parameter."
                    ).to_json()
                language = analysis["language"]
                framework = framework or analysis.get("framework")

            # Normalize language
            language = language.lower()

            # Get appropriate template
            if language not in DOCKERFILE_TEMPLATES:
                return DockerfileGeneratorResult(
                    success=False,
                    project_path=str(path),
                    language=language,
                    error=f"No Dockerfile template for language: {language}. Supported: {list(DOCKERFILE_TEMPLATES.keys())}"
                ).to_json()

            lang_templates = DOCKERFILE_TEMPLATES[language]
            template_key = framework.lower() if framework and framework.lower() in lang_templates else "default"
            template = lang_templates[template_key]

            # Detect entry point
            entrypoint = self._detect_entrypoint(path, language, framework)
            if not entrypoint:
                warnings.append(f"Could not detect entry point. Using default for {language}.")

            # Customize template
            dockerfile_content = self._customize_template(template, path, language, framework, entrypoint)

            # Check for requirements file (Python)
            if language == "python" and not (path / "requirements.txt").exists():
                warnings.append("requirements.txt not found. Create it before building: pip freeze > requirements.txt")

            # Check for package.json (Node)
            if language in ["javascript", "typescript"] and not (path / "package.json").exists():
                warnings.append("package.json not found. Run: npm init")

            # Write Dockerfile
            dockerfile_path.write_text(dockerfile_content)

            logger.info(f"Dockerfile generated: {dockerfile_path}", extra={
                "language": language,
                "framework": framework,
                "entrypoint": entrypoint
            })

            return DockerfileGeneratorResult(
                success=True,
                project_path=str(path),
                dockerfile_path=str(dockerfile_path),
                dockerfile_content=dockerfile_content,
                language=language,
                framework=framework,
                entrypoint_detected=entrypoint,
                port=port,
                already_exists=dockerfile_path.exists() and force,
                overwritten=dockerfile_path.exists() and force,
                warnings=warnings
            ).to_json()

        except Exception as e:
            logger.error(f"Dockerfile generation failed: {e}", exc_info=True)
            return DockerfileGeneratorResult(
                success=False,
                project_path=project_path,
                error=f"{type(e).__name__}: {str(e)}"
            ).to_json()


# =============================================================================
# Requirements Validator Tool
# =============================================================================

class RequirementsValidatorResult(BaseModel):
    """Result of requirements validation"""
    success: bool
    project_path: str
    language: Optional[str] = None
    is_valid: bool = False
    deps_file: Optional[str] = None
    deps_file_exists: bool = False
    lockfile_exists: bool = False
    missing_files: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    dependency_count: int = 0
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class RequirementsValidatorTool(BaseTool):
    """Validate that dependency files exist before deployment

    CRITICAL: Deployments will fail if deps files are missing.
    This tool checks and provides remediation steps.
    """

    # Required files by language
    REQUIRED_FILES = {
        "python": {
            "deps": ["requirements.txt", "pyproject.toml", "Pipfile", "setup.py"],
            "lock": ["requirements.txt", "poetry.lock", "Pipfile.lock"],
            "create_cmd": "pip freeze > requirements.txt"
        },
        "javascript": {
            "deps": ["package.json"],
            "lock": ["package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
            "create_cmd": "npm init -y"
        },
        "typescript": {
            "deps": ["package.json"],
            "lock": ["package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
            "create_cmd": "npm init -y && npm install typescript @types/node"
        },
        "go": {
            "deps": ["go.mod"],
            "lock": ["go.sum"],
            "create_cmd": "go mod init <module-name>"
        },
        "rust": {
            "deps": ["Cargo.toml"],
            "lock": ["Cargo.lock"],
            "create_cmd": "cargo init"
        },
        "java": {
            "deps": ["pom.xml", "build.gradle", "build.gradle.kts"],
            "lock": [],
            "create_cmd": "mvn archetype:generate or gradle init"
        },
        "ruby": {
            "deps": ["Gemfile"],
            "lock": ["Gemfile.lock"],
            "create_cmd": "bundle init"
        }
    }

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="requirements_validator",
                description="Validate dependency files exist before deployment",
                category="code-analysis",
                tags=["validation", "dependencies", "deployment", "devops"]
            )
        )

    def _execute(self, project_path: str = ".", language: Optional[str] = None) -> str:
        """Validate requirements/dependencies files

        Args:
            project_path: Path to project directory
            language: Override language detection

        Returns:
            JSON with validation result
        """
        try:
            path = Path(project_path).resolve()

            if not path.exists() or not path.is_dir():
                return RequirementsValidatorResult(
                    success=False,
                    project_path=str(path),
                    error="Invalid project path"
                ).to_json()

            # Detect language if not provided
            if not language:
                analyzer = TechStackAnalyzerTool()
                analysis = json.loads(analyzer._execute(project_path))
                if not analysis.get("success") or not analysis.get("language"):
                    return RequirementsValidatorResult(
                        success=False,
                        project_path=str(path),
                        error="Could not detect project language"
                    ).to_json()
                language = analysis["language"]

            language = language.lower()

            if language not in self.REQUIRED_FILES:
                return RequirementsValidatorResult(
                    success=False,
                    project_path=str(path),
                    language=language,
                    error=f"Unknown language: {language}"
                ).to_json()

            config = self.REQUIRED_FILES[language]
            warnings = []
            recommendations = []
            missing_files = []

            # Check for dependency file
            deps_file = None
            deps_exists = False
            for df in config["deps"]:
                if (path / df).exists():
                    deps_file = df
                    deps_exists = True
                    break

            if not deps_exists:
                missing_files.extend(config["deps"])
                recommendations.append(f"Create dependency file using: {config['create_cmd']}")

            # Check for lock file
            lockfile_exists = False
            for lf in config["lock"]:
                if (path / lf).exists():
                    lockfile_exists = True
                    break

            if deps_exists and not lockfile_exists and config["lock"]:
                warnings.append("No lock file found. Consider generating one for reproducible builds.")
                if language == "python":
                    recommendations.append("Generate lock: pip freeze > requirements.txt")
                elif language in ["javascript", "typescript"]:
                    recommendations.append("Generate lock: npm install (creates package-lock.json)")

            # Count dependencies
            dep_count = 0
            if deps_exists and deps_file:
                try:
                    if deps_file == "requirements.txt":
                        content = (path / deps_file).read_text()
                        dep_count = len([l for l in content.split("\n") if l.strip() and not l.startswith("#")])
                    elif deps_file == "package.json":
                        data = json.loads((path / deps_file).read_text())
                        dep_count = len(data.get("dependencies", {})) + len(data.get("devDependencies", {}))
                    elif deps_file in ["go.mod", "Cargo.toml", "Gemfile"]:
                        content = (path / deps_file).read_text()
                        dep_count = content.count("\n")  # Rough estimate
                except:
                    pass

            is_valid = deps_exists

            logger.info(f"Requirements validated: {is_valid}", extra={
                "language": language,
                "deps_file": deps_file,
                "dep_count": dep_count
            })

            return RequirementsValidatorResult(
                success=True,
                project_path=str(path),
                language=language,
                is_valid=is_valid,
                deps_file=deps_file,
                deps_file_exists=deps_exists,
                lockfile_exists=lockfile_exists,
                missing_files=missing_files,
                warnings=warnings,
                recommendations=recommendations,
                dependency_count=dep_count
            ).to_json()

        except Exception as e:
            logger.error(f"Requirements validation failed: {e}", exc_info=True)
            return RequirementsValidatorResult(
                success=False,
                project_path=project_path,
                error=f"{type(e).__name__}: {str(e)}"
            ).to_json()


# =============================================================================
# App Config Generator Tool (Procfile, app.yaml)
# =============================================================================

class AppConfigGeneratorResult(BaseModel):
    """Result of app config generation"""
    success: bool
    project_path: str
    config_type: Optional[str] = None
    config_path: Optional[str] = None
    config_content: Optional[str] = None
    language: Optional[str] = None
    framework: Optional[str] = None
    already_exists: bool = False
    overwritten: bool = False
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class AppConfigGeneratorTool(BaseTool):
    """Generate app configuration files (Procfile, app.yaml)

    For platforms that don't use Docker:
    - Heroku: Procfile
    - Google App Engine: app.yaml
    - Railway/Render: can use either
    """

    # Procfile templates
    PROCFILE_TEMPLATES = {
        "python": {
            "default": "web: python main.py",
            "fastapi": "web: uvicorn main:app --host 0.0.0.0 --port $PORT",
            "flask": "web: gunicorn app:app",
            "django": "web: gunicorn config.wsgi:application",
            "streamlit": "web: streamlit run app.py --server.port=$PORT --server.address=0.0.0.0"
        },
        "javascript": {
            "default": "web: node index.js",
            "express": "web: node server.js",
            "nextjs": "web: npm start"
        },
        "typescript": {
            "default": "web: node dist/index.js",
            "nestjs": "web: node dist/main.js"
        },
        "go": {
            "default": "web: ./main",
            "gin": "web: ./main"
        },
        "ruby": {
            "default": "web: bundle exec rails server -p $PORT"
        }
    }

    # App Engine (app.yaml) templates
    APP_YAML_TEMPLATES = {
        "python": """runtime: python311
instance_class: F1
automatic_scaling:
  min_instances: 0
  max_instances: 2
env_variables:
  PORT: "8080"
entrypoint: {entrypoint}
""",
        "javascript": """runtime: nodejs20
instance_class: F1
automatic_scaling:
  min_instances: 0
  max_instances: 2
env_variables:
  PORT: "8080"
""",
        "go": """runtime: go121
instance_class: F1
automatic_scaling:
  min_instances: 0
  max_instances: 2
env_variables:
  PORT: "8080"
"""
    }

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="app_config_generator",
                description="Generate Procfile or app.yaml for non-Docker deployments",
                category="code-analysis",
                tags=["deployment", "heroku", "appengine", "procfile", "devops"]
            )
        )

    def _execute(
        self,
        project_path: str = ".",
        config_type: str = "procfile",
        force: bool = False,
        language: Optional[str] = None,
        framework: Optional[str] = None
    ) -> str:
        """Generate app configuration file

        Args:
            project_path: Path to project directory
            config_type: Type of config ("procfile" or "app.yaml")
            force: Overwrite existing file
            language: Override language detection
            framework: Override framework detection

        Returns:
            JSON with generation result
        """
        try:
            path = Path(project_path).resolve()
            warnings = []

            if not path.exists() or not path.is_dir():
                return AppConfigGeneratorResult(
                    success=False,
                    project_path=str(path),
                    error="Invalid project path"
                ).to_json()

            # Detect language if not provided
            if not language:
                analyzer = TechStackAnalyzerTool()
                analysis = json.loads(analyzer._execute(project_path))
                if not analysis.get("success") or not analysis.get("language"):
                    return AppConfigGeneratorResult(
                        success=False,
                        project_path=str(path),
                        error="Could not detect project language"
                    ).to_json()
                language = analysis["language"]
                framework = framework or analysis.get("framework")

            language = language.lower()
            config_type = config_type.lower()

            # Determine config file path
            if config_type == "procfile":
                config_path = path / "Procfile"
            elif config_type in ["app.yaml", "app_yaml", "appengine"]:
                config_path = path / "app.yaml"
                config_type = "app.yaml"
            else:
                return AppConfigGeneratorResult(
                    success=False,
                    project_path=str(path),
                    error=f"Unknown config type: {config_type}. Use 'procfile' or 'app.yaml'"
                ).to_json()

            # Check if file exists
            if config_path.exists() and not force:
                return AppConfigGeneratorResult(
                    success=False,
                    project_path=str(path),
                    config_type=config_type,
                    already_exists=True,
                    error=f"{config_path.name} already exists. Use force=true to overwrite."
                ).to_json()

            # Generate content
            if config_type == "procfile":
                if language not in self.PROCFILE_TEMPLATES:
                    return AppConfigGeneratorResult(
                        success=False,
                        project_path=str(path),
                        language=language,
                        error=f"No Procfile template for: {language}"
                    ).to_json()

                templates = self.PROCFILE_TEMPLATES[language]
                template_key = framework.lower() if framework and framework.lower() in templates else "default"
                content = templates[template_key]

            else:  # app.yaml
                if language not in self.APP_YAML_TEMPLATES:
                    return AppConfigGeneratorResult(
                        success=False,
                        project_path=str(path),
                        language=language,
                        error=f"No app.yaml template for: {language}"
                    ).to_json()

                content = self.APP_YAML_TEMPLATES[language]

                # Customize entrypoint
                if language == "python":
                    if framework == "fastapi":
                        entrypoint = "gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app"
                    elif framework == "flask":
                        entrypoint = "gunicorn -w 4 app:app"
                    else:
                        entrypoint = "python main.py"
                    content = content.format(entrypoint=entrypoint)

            # Write file
            config_path.write_text(content)

            logger.info(f"App config generated: {config_path}", extra={
                "config_type": config_type,
                "language": language,
                "framework": framework
            })

            return AppConfigGeneratorResult(
                success=True,
                project_path=str(path),
                config_type=config_type,
                config_path=str(config_path),
                config_content=content,
                language=language,
                framework=framework,
                already_exists=config_path.exists() and force,
                overwritten=config_path.exists() and force,
                warnings=warnings
            ).to_json()

        except Exception as e:
            logger.error(f"App config generation failed: {e}", exc_info=True)
            return AppConfigGeneratorResult(
                success=False,
                project_path=project_path,
                error=f"{type(e).__name__}: {str(e)}"
            ).to_json()
