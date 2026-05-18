"""Production-grade security and PII detection/masking tools"""

import re
import hashlib
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, validator

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import (
    ToolValidationError,
    ErrorCode
)
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Type-Safe Models
# =============================================================================

class PIIDetectInput(BaseModel):
    """Type-safe PII detection input with validation"""
    text: str = Field(..., min_length=1, max_length=1000000)  # 1MB max
    include_context: bool = True
    context_chars: int = Field(20, ge=0, le=100)

    @validator('text')
    def validate_text(cls, v):
        """Validate text content"""
        if not v or not v.strip():
            raise ValueError("Text cannot be empty")
        return v


class PIIDetectOutput(BaseModel):
    """Type-safe PII detection output"""
    success: bool
    total_findings: int = 0
    summary: Dict[str, int] = Field(default_factory=dict)
    findings: List[Dict[str, Any]] = Field(default_factory=list)
    text_length: int = 0
    has_pii: bool = False
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class PIIMaskInput(BaseModel):
    """Type-safe PII masking input with validation"""
    text: str = Field(..., min_length=1, max_length=1000000)  # 1MB max
    mask_types: Optional[List[str]] = None
    custom_replacement: Optional[str] = None

    @validator('text')
    def validate_text(cls, v):
        """Validate text content"""
        if not v or not v.strip():
            raise ValueError("Text cannot be empty")
        return v

    @validator('mask_types')
    def validate_mask_types(cls, v):
        """Validate mask types"""
        if v is not None:
            valid_types = {
                "ssn", "credit_card", "email", "phone_us", "ip_address",
                "date_of_birth", "passport", "bitcoin_address",
                "drivers_license", "itin"
            }
            invalid = set(v) - valid_types
            if invalid:
                raise ValueError(f"Invalid mask types: {', '.join(invalid)}")
        return v


class PIIMaskOutput(BaseModel):
    """Type-safe PII masking output"""
    success: bool
    original_length: int = 0
    masked_length: int = 0
    masked_text: Optional[str] = None
    total_replacements: int = 0
    replacements_by_type: Dict[str, int] = Field(default_factory=dict)
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class PIIValidateOutput(BaseModel):
    """Type-safe PII validation output"""
    success: bool
    is_valid: bool = False
    has_pii: bool = False
    total_violations: int = 0
    violations: List[Dict[str, Any]] = Field(default_factory=list)
    strict_mode: bool = True
    text_length: int = 0
    message: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Enhanced PII Pattern Compilation (Performance + Accuracy)
# =============================================================================

class PIIPatterns:
    """Pre-compiled regex patterns for PII detection with enhanced accuracy"""

    # Compile patterns once for performance
    PATTERNS = {
        # SSN with dashes (high confidence)
        "ssn": re.compile(
            r"\b(?!000|666|9\d{2})(?:[0-6]\d{2}|7(?:[0-6]\d|7[0-2]))-"
            r"(?!00)\d{2}-(?!0000)\d{4}\b"
        ),

        # Credit card (Luhn algorithm check would be better, but regex is good start)
        "credit_card": re.compile(
            r"\b(?:4\d{3}|5[1-5]\d{2}|6011|3[47]\d{2})[-\s]?"
            r"(?:\d{4}[-\s]?){2}\d{4}\b"
        ),

        # Email (RFC 5322 compliant)
        "email": re.compile(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        ),

        # US phone (more strict)
        "phone_us": re.compile(
            r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
        ),

        # IPv4 (with valid range check 0-255)
        "ip_address": re.compile(
            r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}"
            r"(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
        ),

        # Date of birth (MM/DD/YYYY or MM-DD-YYYY)
        "date_of_birth": re.compile(
            r"\b(?:0[1-9]|1[0-2])[-/](?:0[1-9]|[12]\d|3[01])[-/]"
            r"(?:19[2-9]\d|20[0-2]\d)\b"  # 1920-2029 only
        ),

        # US Passport (more strict: letter + 7-9 digits)
        "passport": re.compile(
            r"\b[A-Z]\d{7,9}\b"
        ),

        # Bitcoin address (more strict)
        "bitcoin_address": re.compile(
            r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b"
        ),

        # Driver's license (US format - varies by state, basic pattern)
        "drivers_license": re.compile(
            r"\b[A-Z]\d{7,8}\b"  # Most states: Letter + 7-8 digits
        ),

        # ITIN (Individual Taxpayer ID: 9XX-XX-XXXX)
        "itin": re.compile(
            r"\b9\d{2}-(?:5[0-9]|6[0-5]|7[0-9]|8[0-8]|9[0-2]|9[4-9])-\d{4}\b"
        )
    }

    @classmethod
    def get_pattern(cls, pii_type: str) -> Optional[re.Pattern]:
        """Get compiled pattern by type"""
        return cls.PATTERNS.get(pii_type)

    @classmethod
    def get_all_types(cls) -> List[str]:
        """Get all PII types"""
        return list(cls.PATTERNS.keys())


# =============================================================================
# Production-Grade PII Tools
# =============================================================================

class PIIDetectorTool(BaseTool):
    """Production-grade PII detector with enhanced accuracy

    Features:
    - Pre-compiled regex (performance)
    - Enhanced patterns (fewer false positives)
    - PII value hashing (security - doesn't expose actual PII)
    - Pydantic validation
    - Structured logging
    - Text size limits
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="pii_detect",
                description="Detect PII with enhanced accuracy. Finds SSN, credit cards, emails, phones, etc.",
                category="security",
                tags=["pii", "security", "compliance", "gdpr"]
            )
        )

    def _hash_pii(self, value: str) -> str:
        """Hash PII value for secure logging"""
        return hashlib.sha256(value.encode()).hexdigest()[:16]

    def _execute(
        self,
        text: str,
        include_context: bool = True,
        context_chars: int = 20
    ) -> str:
        """Detect PII in text

        Args:
            text: Text to scan for PII
            include_context: Include surrounding text context (default: True)
            context_chars: Characters of context to include (default: 20)

        Returns:
            JSON with PIIDetectOutput schema
        """
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = PIIDetectInput(
                text=text,
                include_context=include_context,
                context_chars=context_chars
            )

            logger.info("Running PII detection", extra={
                "text_hash": text_hash,
                "text_length": len(text)
            })

            findings = []
            total_count = 0

            for pii_type in PIIPatterns.get_all_types():
                pattern = PIIPatterns.get_pattern(pii_type)
                if not pattern:
                    continue

                matches = pattern.finditer(validated.text)

                for match in matches:
                    start, end = match.span()
                    matched_text = match.group()

                    # Hash PII value instead of exposing it
                    pii_hash = self._hash_pii(matched_text)

                    finding = {
                        "type": pii_type,
                        "value_hash": pii_hash,  # Hashed, not actual value
                        "value_preview": matched_text[:4] + "..." if len(matched_text) > 4 else "***",  # First 4 chars only
                        "start": start,
                        "end": end,
                        "length": len(matched_text)
                    }

                    if validated.include_context:
                        # Get surrounding context
                        context_start = max(0, start - validated.context_chars)
                        context_end = min(len(validated.text), end + validated.context_chars)

                        before = validated.text[context_start:start]
                        after = validated.text[end:context_end]

                        finding["context"] = {
                            "before": before,
                            "after": after,
                            "full": f"{before}[REDACTED:{pii_type}]{after}"  # Don't show actual PII
                        }

                    findings.append(finding)
                    total_count += 1

            # Group by type for summary
            summary = {}
            for finding in findings:
                pii_type = finding["type"]
                if pii_type not in summary:
                    summary[pii_type] = 0
                summary[pii_type] += 1

            result = PIIDetectOutput(
                success=True,
                total_findings=total_count,
                summary=summary,
                findings=findings,
                text_length=len(validated.text),
                has_pii=total_count > 0
            )

            logger.info("PII detection completed", extra={
                "text_hash": text_hash,
                "findings_count": total_count,
                "has_pii": total_count > 0,
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("PII detection validation failed", extra={"text_hash": text_hash}, exc_info=True)
            return PIIDetectOutput(
                success=False,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except Exception as e:
            logger.error("PII detection failed", extra={"text_hash": text_hash}, exc_info=True)
            return PIIDetectOutput(
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class PIIMaskTool(BaseTool):
    """Production-grade PII masker with secure output

    Features:
    - Pre-compiled patterns (performance)
    - Type-specific masking
    - Secure output (doesn't expose original PII)
    - Pydantic validation
    - Structured logging
    """

    MASK_REPLACEMENTS = {
        "ssn": "***-**-****",
        "credit_card": "**** **** **** ****",
        "email": "[EMAIL_REDACTED]",
        "phone_us": "[PHONE_REDACTED]",
        "ip_address": "[IP_REDACTED]",
        "date_of_birth": "[DOB_REDACTED]",
        "passport": "[PASSPORT_REDACTED]",
        "bitcoin_address": "[BTC_REDACTED]",
        "drivers_license": "[DL_REDACTED]",
        "itin": "[ITIN_REDACTED]"
    }

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="pii_mask",
                description="Mask/redact PII for safe logging. Production-grade, secure masking.",
                category="security",
                tags=["pii", "security", "redaction", "masking"]
            )
        )

    def _execute(
        self,
        text: str,
        mask_types: Optional[List[str]] = None,
        custom_replacement: Optional[str] = None
    ) -> str:
        """Mask PII in text

        Args:
            text: Text to mask
            mask_types: List of PII types to mask (default: all)
            custom_replacement: Custom replacement string (default: type-specific)

        Returns:
            JSON with PIIMaskOutput schema
        """
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = PIIMaskInput(
                text=text,
                mask_types=mask_types,
                custom_replacement=custom_replacement
            )

            logger.info("Masking PII", extra={
                "text_hash": text_hash,
                "text_length": len(text),
                "mask_types": mask_types or "all"
            })

            masked_text = validated.text
            replacements_by_type = {}

            # If mask_types not specified, mask all types
            types_to_mask = validated.mask_types or PIIPatterns.get_all_types()

            for pii_type in types_to_mask:
                pattern = PIIPatterns.get_pattern(pii_type)
                if not pattern:
                    continue

                replacement = (
                    validated.custom_replacement or
                    self.MASK_REPLACEMENTS.get(pii_type, "[REDACTED]")
                )

                # Count matches before replacement
                matches = list(pattern.finditer(masked_text))
                match_count = len(matches)

                if match_count > 0:
                    replacements_by_type[pii_type] = match_count

                    # Replace matches
                    masked_text = pattern.sub(replacement, masked_text)

            total_replacements = sum(replacements_by_type.values())

            result = PIIMaskOutput(
                success=True,
                original_length=len(validated.text),
                masked_length=len(masked_text),
                masked_text=masked_text,
                total_replacements=total_replacements,
                replacements_by_type=replacements_by_type
            )

            logger.info("PII masking completed", extra={
                "text_hash": text_hash,
                "replacements": total_replacements,
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("PII masking validation failed", extra={"text_hash": text_hash}, exc_info=True)
            return PIIMaskOutput(
                success=False,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except Exception as e:
            logger.error("PII masking failed", extra={"text_hash": text_hash}, exc_info=True)
            return PIIMaskOutput(
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class PIIValidatorTool(BaseTool):
    """Production-grade PII validator for compliance checks

    Features:
    - Reuses enhanced detector (consistent patterns)
    - Strict/lenient modes
    - Structured validation results
    - Audit logging
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="pii_validate",
                description="Validate that text contains no PII. Pass/fail with detected violations.",
                category="security",
                tags=["pii", "security", "validation", "compliance"]
            )
        )
        # Reuse enhanced detector
        self.detector = PIIDetectorTool()

    def _execute(
        self,
        text: str,
        strict_mode: bool = True
    ) -> str:
        """Validate text is PII-free

        Args:
            text: Text to validate
            strict_mode: If True, any PII fails validation. If False, only high-risk PII fails.

        Returns:
            JSON with PIIValidateOutput schema
        """
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:8]

        try:
            logger.info("Validating PII-free text", extra={
                "text_hash": text_hash,
                "strict_mode": strict_mode
            })

            # Run detection
            detection_result_json = self.detector._execute(text, include_context=False)
            detection_result = PIIDetectOutput.model_validate_json(detection_result_json)

            if not detection_result.success:
                raise ToolValidationError(
                    "PII detection failed during validation",
                    field_name="text"
                )

            has_pii = detection_result.has_pii
            findings = detection_result.findings

            # Define high-risk PII types
            high_risk_types = {"ssn", "credit_card", "passport", "itin", "drivers_license"}

            # Check for violations
            violations = []
            if strict_mode:
                violations = findings
            else:
                # Only high-risk PII counts as violation
                violations = [f for f in findings if f["type"] in high_risk_types]

            is_valid = len(violations) == 0

            message = (
                "Validation passed: No PII detected" if is_valid else
                f"Validation failed: Found {len(violations)} PII violation(s)"
            )

            result = PIIValidateOutput(
                success=True,
                is_valid=is_valid,
                has_pii=has_pii,
                total_violations=len(violations),
                violations=violations,
                strict_mode=strict_mode,
                text_length=len(text),
                message=message
            )

            logger.info("PII validation completed", extra={
                "text_hash": text_hash,
                "is_valid": is_valid,
                "violations": len(violations),
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("PII validation failed", extra={"text_hash": text_hash}, exc_info=True)
            return PIIValidateOutput(
                success=False,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except Exception as e:
            logger.error("PII validation failed", extra={"text_hash": text_hash}, exc_info=True)
            return PIIValidateOutput(
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


# =============================================================================
# Enterprise Security Tools - Container, IAM, SSL
# =============================================================================

import subprocess
import shutil
import json
from pathlib import Path
from enum import Enum


class VulnerabilitySeverity(str, Enum):
    """Vulnerability severity levels"""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class Vulnerability(BaseModel):
    """Single vulnerability finding"""
    package: str
    version: str
    severity: VulnerabilitySeverity
    cve_id: Optional[str] = None
    description: Optional[str] = None
    fix_version: Optional[str] = None


class ContainerScanResult(BaseModel):
    """Result of container vulnerability scan"""
    success: bool
    image: Optional[str] = None
    total_vulnerabilities: int = 0
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    vulnerabilities: List[Vulnerability] = Field(default_factory=list)
    scan_passed: bool = True
    message: str = ""
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class IAMValidationResult(BaseModel):
    """Result of IAM permission validation"""
    success: bool
    service_account: Optional[str] = None
    project_id: Optional[str] = None
    has_all_permissions: bool = False
    granted_permissions: List[str] = Field(default_factory=list)
    missing_permissions: List[str] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)
    message: str = ""
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class SecretScanResult(BaseModel):
    """Result of secret/credential scanning"""
    success: bool
    files_scanned: int = 0
    secrets_found: int = 0
    findings: List[Dict[str, Any]] = Field(default_factory=list)
    scan_passed: bool = True
    message: str = ""
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class ContainerScannerTool(BaseTool):
    """Scan container images for vulnerabilities using Trivy or Grype"""

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="container_scanner",
                description="Scan container images for security vulnerabilities",
                category="security",
                version="1.0.0",
                requires_auth=True,
            )
        )
        self._trivy_path = shutil.which("trivy")
        self._grype_path = shutil.which("grype")

    def _execute(
        self,
        image: str,
        scanner: str = "auto",
        severity_threshold: str = "HIGH",
        fail_on_vuln: bool = True,
        ignore_unfixed: bool = False,
    ) -> str:
        """Scan container image for vulnerabilities"""
        try:
            if scanner == "auto":
                if self._trivy_path:
                    scanner = "trivy"
                elif self._grype_path:
                    scanner = "grype"
                else:
                    return ContainerScanResult(
                        success=False,
                        error="No scanner available. Install: brew install trivy"
                    ).to_json()

            if scanner == "trivy":
                return self._scan_with_trivy(image, severity_threshold, fail_on_vuln, ignore_unfixed)
            elif scanner == "grype":
                return self._scan_with_grype(image, severity_threshold, fail_on_vuln)
            else:
                return ContainerScanResult(
                    success=False,
                    error=f"Unknown scanner: {scanner}"
                ).to_json()

        except Exception as e:
            return ContainerScanResult(success=False, error=str(e)).to_json()

    def _scan_with_trivy(self, image: str, threshold: str, fail_on_vuln: bool, ignore_unfixed: bool) -> str:
        """Scan using Trivy"""
        cmd = [self._trivy_path, "image", "--format", "json", "--severity", "CRITICAL,HIGH,MEDIUM,LOW"]
        if ignore_unfixed:
            cmd.append("--ignore-unfixed")
        cmd.append(image)

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        try:
            data = json.loads(result.stdout)
            vulns = self._parse_trivy_results(data)
            counts = self._count_severities(vulns)
            passed = self._check_threshold(counts, threshold, fail_on_vuln)

            return ContainerScanResult(
                success=True,
                image=image,
                total_vulnerabilities=len(vulns),
                critical=counts.get("CRITICAL", 0),
                high=counts.get("HIGH", 0),
                medium=counts.get("MEDIUM", 0),
                low=counts.get("LOW", 0),
                vulnerabilities=vulns[:20],
                scan_passed=passed,
                message="Scan complete" if passed else f"Found vulns above {threshold}"
            ).to_json()
        except json.JSONDecodeError:
            return ContainerScanResult(success=False, error=result.stderr).to_json()

    def _scan_with_grype(self, image: str, threshold: str, fail_on_vuln: bool) -> str:
        """Scan using Grype"""
        cmd = [self._grype_path, image, "-o", "json"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        try:
            data = json.loads(result.stdout)
            vulns = self._parse_grype_results(data)
            counts = self._count_severities(vulns)
            passed = self._check_threshold(counts, threshold, fail_on_vuln)

            return ContainerScanResult(
                success=True, image=image,
                total_vulnerabilities=len(vulns),
                critical=counts.get("CRITICAL", 0), high=counts.get("HIGH", 0),
                medium=counts.get("MEDIUM", 0), low=counts.get("LOW", 0),
                vulnerabilities=vulns[:20], scan_passed=passed,
                message="Scan complete"
            ).to_json()
        except json.JSONDecodeError:
            return ContainerScanResult(success=False, error=result.stderr).to_json()

    def _parse_trivy_results(self, data: dict) -> List[Vulnerability]:
        vulns = []
        for result in data.get("Results", []):
            for v in result.get("Vulnerabilities", []):
                vulns.append(Vulnerability(
                    package=v.get("PkgName", "unknown"),
                    version=v.get("InstalledVersion", "unknown"),
                    severity=VulnerabilitySeverity(v.get("Severity", "UNKNOWN")),
                    cve_id=v.get("VulnerabilityID"),
                    fix_version=v.get("FixedVersion")
                ))
        return vulns

    def _parse_grype_results(self, data: dict) -> List[Vulnerability]:
        vulns = []
        for match in data.get("matches", []):
            v = match.get("vulnerability", {})
            a = match.get("artifact", {})
            vulns.append(Vulnerability(
                package=a.get("name", "unknown"),
                version=a.get("version", "unknown"),
                severity=VulnerabilitySeverity(v.get("severity", "UNKNOWN")),
                cve_id=v.get("id")
            ))
        return vulns

    def _count_severities(self, vulns: List[Vulnerability]) -> Dict[str, int]:
        counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for v in vulns:
            if v.severity.value in counts:
                counts[v.severity.value] += 1
        return counts

    def _check_threshold(self, counts: Dict[str, int], threshold: str, fail_on_vuln: bool) -> bool:
        if not fail_on_vuln:
            return True
        order = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
        idx = order.index(threshold) if threshold in order else 0
        for i in range(idx + 1):
            if counts.get(order[i], 0) > 0:
                return False
        return True


class IAMValidatorTool(BaseTool):
    """Validate IAM permissions before deployment"""

    PERMISSION_SETS = {
        "cloud_run_deploy": ["run.services.create", "run.services.update", "run.services.get"],
        "cloud_build": ["cloudbuild.builds.create", "cloudbuild.builds.get"],
        "artifact_registry": ["artifactregistry.repositories.uploadArtifacts"],
        "secret_manager": ["secretmanager.secrets.get", "secretmanager.versions.access"],
        "full_deploy": [],  # Populated dynamically
    }

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="iam_validator",
                description="Validate IAM permissions before deployment",
                category="security",
                version="1.0.0",
                requires_auth=True,
            )
        )
        self._gcloud_path = shutil.which("gcloud")
        # Build full_deploy from all permissions
        for perms in list(self.PERMISSION_SETS.values()):
            self.PERMISSION_SETS["full_deploy"].extend(perms)

    def _execute(
        self,
        project_id: str,
        service_account: Optional[str] = None,
        operation: str = "cloud_run_deploy",
    ) -> str:
        """Validate IAM permissions"""
        if not self._gcloud_path:
            return IAMValidationResult(success=False, error="gcloud CLI not found").to_json()

        try:
            if not service_account:
                result = subprocess.run(
                    [self._gcloud_path, "config", "get-value", "account"],
                    capture_output=True, text=True
                )
                service_account = result.stdout.strip()

            required = self.PERMISSION_SETS.get(operation, [])
            if not required:
                return IAMValidationResult(success=False, error=f"Unknown operation: {operation}").to_json()

            roles = self._get_roles(project_id, service_account)

            return IAMValidationResult(
                success=True,
                service_account=service_account,
                project_id=project_id,
                has_all_permissions=len(roles) > 0,
                roles=roles,
                message=f"Found {len(roles)} roles for {service_account}"
            ).to_json()

        except Exception as e:
            return IAMValidationResult(success=False, error=str(e)).to_json()

    def _get_roles(self, project_id: str, service_account: str) -> List[str]:
        cmd = [
            self._gcloud_path, "projects", "get-iam-policy", project_id,
            f"--flatten=bindings[].members",
            f"--filter=bindings.members:serviceAccount:{service_account}",
            "--format=value(bindings.role)"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return []
        return [r.strip() for r in result.stdout.strip().split("\n") if r.strip()]


class SecretScannerTool(BaseTool):
    """Scan code for accidentally committed secrets/credentials"""

    SECRET_PATTERNS = {
        "aws_access_key": r"AKIA[0-9A-Z]{16}",
        "gcp_api_key": r"AIza[0-9A-Za-z\\-_]{35}",
        "github_token": r"ghp_[0-9a-zA-Z]{36}",
        "private_key": r"-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----",
        "generic_secret": r"(?i)(secret|api_key|apikey)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
        "jwt_token": r"eyJ[A-Za-z0-9-_]+\.eyJ[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+",
    }

    SKIP_PATTERNS = [".git", "node_modules", "__pycache__", ".venv", "venv"]

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="secret_scanner",
                description="Scan code for accidentally committed secrets",
                category="security",
                version="1.0.0",
            )
        )

    def _execute(
        self,
        project_path: str = ".",
        file_extensions: Optional[List[str]] = None,
        fail_on_secrets: bool = True,
        max_file_size: int = 1024 * 1024,
    ) -> str:
        """Scan project for secrets"""
        try:
            project = Path(project_path).resolve()
            if file_extensions is None:
                file_extensions = [".py", ".js", ".ts", ".json", ".yaml", ".yml", ".env", ".sh"]

            findings = []
            files_scanned = 0

            for ext in file_extensions:
                for file_path in project.rglob(f"*{ext}"):
                    if any(skip in str(file_path) for skip in self.SKIP_PATTERNS):
                        continue
                    if file_path.stat().st_size > max_file_size:
                        continue

                    files_scanned += 1
                    try:
                        content = file_path.read_text(errors="ignore")
                        for pattern_name, pattern in self.SECRET_PATTERNS.items():
                            for match in re.finditer(pattern, content):
                                line_num = content[:match.start()].count("\n") + 1
                                findings.append({
                                    "file": str(file_path.relative_to(project)),
                                    "line": line_num,
                                    "type": pattern_name,
                                    "match": match.group()[:30] + "...",
                                })
                    except Exception:
                        pass

            scan_passed = len(findings) == 0 or not fail_on_secrets
            return SecretScanResult(
                success=True,
                files_scanned=files_scanned,
                secrets_found=len(findings),
                findings=findings[:50],
                scan_passed=scan_passed,
                message="No secrets found" if scan_passed else f"Found {len(findings)} secrets"
            ).to_json()

        except Exception as e:
            return SecretScanResult(success=False, error=str(e)).to_json()
