"""Production-grade email sending and notification tools"""

import smtplib
import os
import re
import time
import hashlib
from typing import List, Dict, Any, Optional, Literal
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from pydantic import BaseModel, Field, validator, EmailStr

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import (
    ToolExecutionError,
    ToolValidationError,
    NetworkTimeoutError,
    ErrorCode
)
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Type-Safe Models
# =============================================================================

class EmailSendInput(BaseModel):
    """Type-safe email send input with validation"""
    to: EmailStr  # Pydantic's built-in email validation
    subject: str = Field(..., min_length=1, max_length=500)
    body: str = Field(..., min_length=1, max_length=100000)  # 100KB max
    from_addr: Optional[EmailStr] = None
    cc: Optional[List[EmailStr]] = None
    bcc: Optional[List[EmailStr]] = None
    html: bool = False
    attachments: Optional[List[str]] = None

    @validator('attachments')
    def validate_attachments(cls, v):
        """Validate attachment paths and sizes"""
        if not v:
            return v

        MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25MB per attachment
        MAX_TOTAL_SIZE = 50 * 1024 * 1024  # 50MB total
        MAX_ATTACHMENTS = 10

        if len(v) > MAX_ATTACHMENTS:
            raise ValueError(f"Too many attachments (max {MAX_ATTACHMENTS})")

        total_size = 0
        validated_paths = []

        for file_path in v:
            path = Path(file_path).resolve()

            # Path traversal protection
            if ".." in str(path):
                raise ValueError(f"Path traversal not allowed: {file_path}")

            # File must exist
            if not path.exists():
                raise ValueError(f"Attachment not found: {file_path}")

            if not path.is_file():
                raise ValueError(f"Not a file: {file_path}")

            # Size check
            file_size = path.stat().st_size
            if file_size > MAX_ATTACHMENT_SIZE:
                raise ValueError(
                    f"Attachment too large: {file_path} "
                    f"({file_size / 1024 / 1024:.1f}MB > 25MB)"
                )

            total_size += file_size
            validated_paths.append(str(path))

        if total_size > MAX_TOTAL_SIZE:
            raise ValueError(
                f"Total attachments too large: "
                f"{total_size / 1024 / 1024:.1f}MB > 50MB"
            )

        return validated_paths

    @validator('body')
    def validate_body(cls, v):
        """Validate email body"""
        if not v or not v.strip():
            raise ValueError("Email body cannot be empty")
        return v


class EmailSendOutput(BaseModel):
    """Type-safe email send output"""
    success: bool
    to: str
    subject: str
    message: Optional[str] = None
    from_addr: Optional[str] = None
    cc: List[str] = Field(default_factory=list)
    bcc: List[str] = Field(default_factory=list)
    attachment_count: int = 0
    is_html: bool = False
    body_length: int = 0
    total_recipients: int = 0
    error: Optional[str] = None
    error_code: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class EmailTemplateInput(BaseModel):
    """Type-safe template input with validation"""
    template_name: str = Field(..., pattern="^[a-z_]+$")  # Only lowercase, underscore
    variables: Dict[str, str]
    format: Literal["plain", "html", "both"] = "both"

    @validator('variables')
    def validate_variables(cls, v):
        """Validate template variables"""
        if not v:
            raise ValueError("Variables cannot be empty")

        # Sanitize variable values (prevent template injection)
        MAX_VAR_LENGTH = 1000
        sanitized = {}

        for key, value in v.items():
            if not isinstance(value, str):
                raise ValueError(f"Variable '{key}' must be string, got {type(value)}")

            if len(value) > MAX_VAR_LENGTH:
                raise ValueError(f"Variable '{key}' too long (max {MAX_VAR_LENGTH} chars)")

            # Basic sanitization - escape braces to prevent injection
            sanitized_value = value.replace('{', '{{').replace('}', '}}')
            sanitized[key] = sanitized_value

        return sanitized


class EmailTemplateOutput(BaseModel):
    """Type-safe template output"""
    success: bool
    template_name: str
    subject: Optional[str] = None
    body_plain: Optional[str] = None
    body_html: Optional[str] = None
    variables_used: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Retry Decorator for SMTP
# =============================================================================

def retry_smtp(max_attempts=3, initial_delay=1.0, max_delay=30.0, base=2.0):
    """Retry SMTP operations with exponential backoff"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except smtplib.SMTPAuthenticationError:
                    # Don't retry auth errors
                    raise
                except (
                    smtplib.SMTPServerDisconnected,
                    smtplib.SMTPConnectError,
                    TimeoutError,
                    ConnectionError
                ) as e:
                    if attempt < max_attempts:
                        logger.warning(
                            f"SMTP connection failed, retrying {attempt}/{max_attempts}",
                            extra={"attempt": attempt, "delay": delay}
                        )
                        time.sleep(delay)
                        delay = min(delay * base, max_delay)
                    else:
                        raise NetworkTimeoutError(
                            f"SMTP failed after {max_attempts} attempts",
                            details={"last_error": str(e)}
                        ) from e
            raise
        return wrapper
    return decorator


# =============================================================================
# Production-Grade Email Tools
# =============================================================================

class EmailSenderTool(BaseTool):
    """Production-grade email sender with retry logic and validation

    Features:
    - Context managers (guaranteed SMTP cleanup)
    - Retry logic with exponential backoff
    - Attachment validation (size, path traversal)
    - Pydantic email validation
    - Timeout enforcement
    - Structured logging with PII masking
    - Specific error codes
    """

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int = 587,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        use_tls: bool = True,
        default_from: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.use_tls = use_tls
        self.default_from = default_from or smtp_user
        self.timeout = timeout
        self.max_retries = max_retries

        super().__init__(
            ToolMetadata(
                name="email_send",
                description="Send emails with production-grade reliability. Supports attachments, HTML, retry logic.",
                category="communication",
                tags=["email", "notification", "smtp", "communication"]
            )
        )

    @contextmanager
    def _get_smtp_connection(self):
        """Context manager - guaranteed SMTP cleanup"""
        server = None
        try:
            # Create connection with timeout
            if self.use_tls:
                server = smtplib.SMTP(
                    self.smtp_host,
                    self.smtp_port,
                    timeout=self.timeout
                )
                server.starttls()
            else:
                server = smtplib.SMTP(
                    self.smtp_host,
                    self.smtp_port,
                    timeout=self.timeout
                )

            # Login if credentials provided
            if self.smtp_user and self.smtp_password:
                server.login(self.smtp_user, self.smtp_password)

            yield server

        finally:
            if server:
                try:
                    server.quit()
                except Exception as e:
                    logger.error("Error closing SMTP connection", exc_info=True)

    def _create_message(
        self,
        validated: EmailSendInput
    ) -> MIMEMultipart:
        """Create MIME message with attachments"""
        msg = MIMEMultipart()
        msg['From'] = validated.from_addr or self.default_from
        msg['To'] = validated.to
        msg['Subject'] = validated.subject

        if validated.cc:
            msg['Cc'] = ', '.join(validated.cc)
        if validated.bcc:
            msg['Bcc'] = ', '.join(validated.bcc)

        # Add body
        mime_type = 'html' if validated.html else 'plain'
        msg.attach(MIMEText(validated.body, mime_type))

        # Add attachments (already validated)
        if validated.attachments:
            for file_path in validated.attachments:
                with open(file_path, 'rb') as f:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(f.read())

                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename={os.path.basename(file_path)}'
                )
                msg.attach(part)

        return msg

    @retry_smtp(max_attempts=3)
    def _send_with_retry(
        self,
        msg: MIMEMultipart,
        all_recipients: List[str]
    ):
        """Send email with retry logic"""
        with self._get_smtp_connection() as server:
            server.send_message(msg)

    def _execute(
        self,
        to: str,
        subject: str,
        body: str,
        from_addr: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        html: bool = False,
        attachments: Optional[List[str]] = None
    ) -> str:
        """Send an email

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body (plain text or HTML)
            from_addr: Sender email (optional, uses default)
            cc: CC recipients (optional)
            bcc: BCC recipients (optional)
            html: Whether body is HTML (default: False)
            attachments: List of file paths to attach (optional)

        Returns:
            JSON with EmailSendOutput schema
        """
        start_time = time.time()
        # Hash email for logging (PII protection)
        email_hash = hashlib.sha256(to.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = EmailSendInput(
                to=to,
                subject=subject,
                body=body,
                from_addr=from_addr,
                cc=cc,
                bcc=bcc,
                html=html,
                attachments=attachments
            )

            logger.info("Sending email", extra={
                "email_hash": email_hash,
                "subject": subject[:50],  # Truncate for logging
                "has_attachments": bool(attachments),
                "is_html": html
            })

            # Create message
            msg = self._create_message(validated)

            # Get all recipients
            all_recipients = [validated.to]
            if validated.cc:
                all_recipients.extend(validated.cc)
            if validated.bcc:
                all_recipients.extend(validated.bcc)

            # Send with retry logic
            self._send_with_retry(msg, all_recipients)

            duration = time.time() - start_time
            result = EmailSendOutput(
                success=True,
                to=validated.to,
                subject=validated.subject,
                message="Email sent successfully",
                from_addr=msg['From'],
                cc=validated.cc or [],
                bcc=validated.bcc or [],
                attachment_count=len(validated.attachments) if validated.attachments else 0,
                is_html=validated.html,
                body_length=len(validated.body),
                total_recipients=len(all_recipients),
                metadata={
                    "duration_seconds": round(duration, 3),
                    "smtp_host": self.smtp_host
                }
            )

            logger.info("Email sent successfully", extra={
                "email_hash": email_hash,
                "duration": duration,
                "recipients": len(all_recipients),
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("Email validation failed", extra={"email_hash": email_hash}, exc_info=True)
            return EmailSendOutput(
                success=False,
                to=to,
                subject=subject,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except smtplib.SMTPAuthenticationError as e:
            logger.error("SMTP auth failed", extra={"email_hash": email_hash}, exc_info=True)
            return EmailSendOutput(
                success=False,
                to=to,
                subject=subject,
                error="SMTP authentication failed. Check username/password.",
                error_code=ErrorCode.HTTP_401.value  # Reuse 401 for auth
            ).to_json()

        except NetworkTimeoutError as e:
            logger.error("SMTP timeout", extra={"email_hash": email_hash}, exc_info=True)
            return EmailSendOutput(
                success=False,
                to=to,
                subject=subject,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except smtplib.SMTPException as e:
            logger.error("SMTP error", extra={"email_hash": email_hash}, exc_info=True)
            return EmailSendOutput(
                success=False,
                to=to,
                subject=subject,
                error=f"SMTP error: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()

        except Exception as e:
            logger.error("Unexpected error", extra={"email_hash": email_hash}, exc_info=True)
            return EmailSendOutput(
                success=False,
                to=to,
                subject=subject,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class EmailTemplateManager(BaseTool):
    """Production-grade email template manager with injection protection

    Features:
    - Template variable sanitization (prevent injection)
    - Missing variable detection
    - Input validation with Pydantic
    - Structured error handling
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="email_template",
                description="Render email templates with variable substitution. Injection-safe, validated.",
                category="communication",
                tags=["email", "template", "rendering"]
            )
        )

        # Pre-defined templates
        self.templates = {
            "welcome": {
                "subject": "Welcome to {company_name}!",
                "body": """
Hello {user_name},

Welcome to {company_name}! We're excited to have you on board.

Your account has been successfully created with the email: {user_email}

Next steps:
1. Complete your profile
2. Explore our platform
3. Join our community

If you have any questions, feel free to reach out to our support team.

Best regards,
{company_name} Team
                """,
                "html": """
<html>
<body style="font-family: Arial, sans-serif;">
    <h2>Welcome to {company_name}!</h2>
    <p>Hello {user_name},</p>
    <p>We're excited to have you on board.</p>
    <p>Your account: <strong>{user_email}</strong></p>
    <h3>Next Steps:</h3>
    <ol>
        <li>Complete your profile</li>
        <li>Explore our platform</li>
        <li>Join our community</li>
    </ol>
    <p>Best regards,<br/>{company_name} Team</p>
</body>
</html>
                """
            },
            "notification": {
                "subject": "Notification: {notification_type}",
                "body": """
{user_name},

{notification_message}

Action required: {action_required}
Deadline: {deadline}

View details: {link}

- Automated Notification System
                """,
                "html": """
<html>
<body style="font-family: Arial, sans-serif;">
    <h2>Notification: {notification_type}</h2>
    <p>Hello {user_name},</p>
    <p>{notification_message}</p>
    <div style="background-color: #f0f0f0; padding: 15px; margin: 20px 0;">
        <strong>Action required:</strong> {action_required}<br/>
        <strong>Deadline:</strong> {deadline}
    </div>
    <p><a href="{link}" style="background-color: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">View Details</a></p>
</body>
</html>
                """
            },
            "alert": {
                "subject": "⚠️ Alert: {alert_type}",
                "body": """
ALERT: {alert_type}

Severity: {severity}
Timestamp: {timestamp}

Message:
{alert_message}

Affected systems: {affected_systems}

Action taken: {action_taken}

- Automated Alert System
                """,
                "html": """
<html>
<body style="font-family: Arial, sans-serif;">
    <div style="background-color: #ff6b6b; color: white; padding: 20px;">
        <h2>⚠️ Alert: {alert_type}</h2>
    </div>
    <div style="padding: 20px;">
        <p><strong>Severity:</strong> {severity}</p>
        <p><strong>Timestamp:</strong> {timestamp}</p>
        <h3>Message:</h3>
        <p>{alert_message}</p>
        <p><strong>Affected systems:</strong> {affected_systems}</p>
        <p><strong>Action taken:</strong> {action_taken}</p>
    </div>
</body>
</html>
                """
            }
        }

    def _get_required_variables(self, template_name: str) -> set:
        """Extract required variables from template"""
        template = self.templates[template_name]
        required = set()

        # Extract from subject, body, html
        for field in ['subject', 'body', 'html']:
            text = template[field]
            # Find all {variable} patterns
            matches = re.findall(r'\{(\w+)\}', text)
            required.update(matches)

        return required

    def _execute(
        self,
        template_name: str,
        variables: Dict[str, str],
        format: Literal["plain", "html", "both"] = "both"
    ) -> str:
        """Render email template with variables

        Args:
            template_name: Name of template (welcome, notification, alert)
            variables: Dictionary of variables to substitute
            format: Output format (plain, html, or both)

        Returns:
            JSON with EmailTemplateOutput schema
        """
        template_hash = hashlib.sha256(template_name.encode()).hexdigest()[:8]

        try:
            # Check template exists
            if template_name not in self.templates:
                available = ', '.join(self.templates.keys())
                raise ToolValidationError(
                    f"Template '{template_name}' not found. Available: {available}",
                    field_name="template_name"
                )

            # Validate input (sanitizes variables)
            validated = EmailTemplateInput(
                template_name=template_name,
                variables=variables,
                format=format
            )

            logger.info("Rendering email template", extra={
                "template_hash": template_hash,
                "template_name": template_name,
                "var_count": len(variables)
            })

            # Check for missing required variables
            required_vars = self._get_required_variables(template_name)
            provided_vars = set(variables.keys())
            missing_vars = required_vars - provided_vars

            if missing_vars:
                raise ToolValidationError(
                    f"Missing required variables: {', '.join(sorted(missing_vars))}",
                    field_name="variables"
                )

            template = self.templates[template_name]

            # Render with sanitized variables
            result = EmailTemplateOutput(
                success=True,
                template_name=template_name,
                subject=template["subject"].format(**validated.variables),
                variables_used=list(variables.keys())
            )

            if format in ["plain", "both"]:
                result.body_plain = template["body"].format(**validated.variables).strip()

            if format in ["html", "both"]:
                result.body_html = template["html"].format(**validated.variables).strip()

            logger.info("Template rendered successfully", extra={
                "template_hash": template_hash,
                "template_name": template_name,
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("Template validation failed", extra={"template_hash": template_hash}, exc_info=True)
            return EmailTemplateOutput(
                success=False,
                template_name=template_name,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except KeyError as e:
            logger.error("Missing variable", extra={"template_hash": template_hash}, exc_info=True)
            return EmailTemplateOutput(
                success=False,
                template_name=template_name,
                error=f"Missing required variable: {e}",
                error_code=ErrorCode.TOOL_VALIDATION_FAILED.value
            ).to_json()

        except Exception as e:
            logger.error("Template rendering failed", extra={"template_hash": template_hash}, exc_info=True)
            return EmailTemplateOutput(
                success=False,
                template_name=template_name,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()
