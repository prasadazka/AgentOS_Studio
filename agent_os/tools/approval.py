"""
Human-in-the-Loop (HITL) Approval System for Agent_OS

Provides approval decorators and approval managers for dangerous operations:
- Interactive approval prompts
- Approval history tracking
- Configurable approval modes (auto-approve, auto-deny, interactive)
- Audit logging for compliance
"""

import json
import time
from typing import Optional, Callable, Any, Dict, List
from functools import wraps
from enum import Enum
from datetime import datetime
from pathlib import Path

from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Approval System
# =============================================================================

class ApprovalMode(str, Enum):
    """Approval modes for operations"""
    INTERACTIVE = "interactive"  # Prompt user for approval
    AUTO_APPROVE = "auto_approve"  # Automatically approve all
    AUTO_DENY = "auto_deny"  # Automatically deny all
    WHITELIST = "whitelist"  # Auto-approve whitelisted patterns only


class ApprovalDecision(str, Enum):
    """Approval decision outcomes"""
    APPROVED = "approved"
    DENIED = "denied"
    TIMEOUT = "timeout"
    ERROR = "error"


class ApprovalRecord:
    """Record of an approval decision"""

    def __init__(
        self,
        operation: str,
        description: str,
        decision: ApprovalDecision,
        reason: Optional[str] = None,
        user: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.operation = operation
        self.description = description
        self.decision = decision
        self.reason = reason
        self.user = user or "system"
        self.timestamp = datetime.now().isoformat()
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation": self.operation,
            "description": self.description,
            "decision": self.decision.value,
            "reason": self.reason,
            "user": self.user,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


class ApprovalManager:
    """
    Manages approval decisions and audit trail

    Features:
    - Multiple approval modes
    - Approval history tracking
    - Pattern-based whitelisting
    - Audit log persistence
    """

    def __init__(
        self,
        mode: ApprovalMode = ApprovalMode.INTERACTIVE,
        whitelist: Optional[List[str]] = None,
        audit_log_path: Optional[str] = None
    ):
        """
        Initialize approval manager

        Args:
            mode: Approval mode (interactive/auto_approve/auto_deny/whitelist)
            whitelist: List of whitelisted operation patterns (for whitelist mode)
            audit_log_path: Path to audit log file (optional)
        """
        self.mode = mode
        self.whitelist = whitelist or []
        self.audit_log_path = audit_log_path
        self.history: List[ApprovalRecord] = []

    def request_approval(
        self,
        operation: str,
        description: str,
        details: Optional[Dict[str, Any]] = None,
        timeout: int = 60
    ) -> tuple[ApprovalDecision, Optional[str]]:
        """
        Request approval for an operation

        Args:
            operation: Operation name/type
            description: Human-readable description
            details: Additional operation details
            timeout: Timeout in seconds for interactive mode

        Returns:
            (decision, reason)
        """
        details = details or {}

        # Check mode
        if self.mode == ApprovalMode.AUTO_APPROVE:
            decision = ApprovalDecision.APPROVED
            reason = "Auto-approved (approval mode: auto_approve)"
            self._record_decision(operation, description, decision, reason, details)
            return decision, reason

        elif self.mode == ApprovalMode.AUTO_DENY:
            decision = ApprovalDecision.DENIED
            reason = "Auto-denied (approval mode: auto_deny)"
            self._record_decision(operation, description, decision, reason, details)
            return decision, reason

        elif self.mode == ApprovalMode.WHITELIST:
            # Check if operation matches whitelist
            if self._is_whitelisted(operation):
                decision = ApprovalDecision.APPROVED
                reason = "Whitelisted operation"
                self._record_decision(operation, description, decision, reason, details)
                return decision, reason
            else:
                decision = ApprovalDecision.DENIED
                reason = "Not in whitelist"
                self._record_decision(operation, description, decision, reason, details)
                return decision, reason

        else:  # INTERACTIVE mode
            return self._interactive_approval(operation, description, details, timeout)

    def _interactive_approval(
        self,
        operation: str,
        description: str,
        details: Dict[str, Any],
        timeout: int
    ) -> tuple[ApprovalDecision, Optional[str]]:
        """Prompt user for approval interactively"""

        print("\n" + "="*80)
        print("⚠️  APPROVAL REQUIRED")
        print("="*80)
        print(f"Operation: {operation}")
        print(f"Description: {description}")

        if details:
            print(f"\nDetails:")
            for key, value in details.items():
                # Truncate long values
                value_str = str(value)
                if len(value_str) > 100:
                    value_str = value_str[:100] + "..."
                print(f"  {key}: {value_str}")

        print("\nDo you approve this operation?")
        print("  [y] Yes, approve")
        print("  [n] No, deny")
        print("  [d] Deny and show details")
        print("="*80)

        try:
            # Get user input with timeout
            import sys
            if sys.platform == "win32":
                # Windows doesn't support select() on stdin, use simple input
                response = input("Your decision [y/n/d]: ").strip().lower()
            else:
                # Unix-like systems can use select for timeout
                import select
                print("Your decision [y/n/d]: ", end='', flush=True)
                ready, _, _ = select.select([sys.stdin], [], [], timeout)
                if ready:
                    response = sys.stdin.readline().strip().lower()
                else:
                    print("\n⏱️  Timeout - operation denied by default")
                    decision = ApprovalDecision.TIMEOUT
                    reason = f"No response within {timeout}s timeout"
                    self._record_decision(operation, description, decision, reason, details)
                    return decision, reason

            if response == 'y' or response == 'yes':
                decision = ApprovalDecision.APPROVED
                reason = "User approved"
                print("✅ Approved")
            elif response == 'd' or response == 'details':
                print("\n📋 Full Details:")
                print(json.dumps(details, indent=2))
                print("\nApprove after seeing details? [y/n]: ", end='', flush=True)
                response2 = input().strip().lower()
                if response2 == 'y' or response2 == 'yes':
                    decision = ApprovalDecision.APPROVED
                    reason = "User approved after reviewing details"
                    print("✅ Approved")
                else:
                    decision = ApprovalDecision.DENIED
                    reason = "User denied after reviewing details"
                    print("❌ Denied")
            else:
                decision = ApprovalDecision.DENIED
                reason = "User denied"
                print("❌ Denied")

        except Exception as e:
            logger.error(f"Approval prompt error: {e}", exc_info=True)
            decision = ApprovalDecision.ERROR
            reason = f"Error during approval: {str(e)}"
            print(f"❌ Error: {reason}")

        self._record_decision(operation, description, decision, reason, details)
        return decision, reason

    def _is_whitelisted(self, operation: str) -> bool:
        """Check if operation matches whitelist patterns"""
        import re
        for pattern in self.whitelist:
            if re.search(pattern, operation, re.IGNORECASE):
                return True
        return False

    def _record_decision(
        self,
        operation: str,
        description: str,
        decision: ApprovalDecision,
        reason: Optional[str],
        metadata: Dict[str, Any]
    ):
        """Record approval decision for audit trail"""
        record = ApprovalRecord(
            operation=operation,
            description=description,
            decision=decision,
            reason=reason,
            metadata=metadata
        )

        self.history.append(record)

        # Log to audit file if configured
        if self.audit_log_path:
            self._write_to_audit_log(record)

        # Log to system logger
        logger.info(f"Approval decision", extra={
            "operation": operation,
            "decision": decision.value,
            "reason": reason
        })

    def _write_to_audit_log(self, record: ApprovalRecord):
        """Write approval record to audit log file"""
        try:
            log_path = Path(self.audit_log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            with open(log_path, 'a') as f:
                f.write(record.to_json() + "\n")
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}", exc_info=True)

    def get_history(self, limit: int = 100) -> List[ApprovalRecord]:
        """Get approval history"""
        return self.history[-limit:]

    def clear_history(self):
        """Clear approval history"""
        self.history.clear()


# Global approval manager instance
_global_approval_manager: Optional[ApprovalManager] = None


def get_approval_manager() -> ApprovalManager:
    """Get global approval manager (creates if not exists)"""
    global _global_approval_manager
    if _global_approval_manager is None:
        _global_approval_manager = ApprovalManager(mode=ApprovalMode.INTERACTIVE)
    return _global_approval_manager


def set_approval_manager(manager: ApprovalManager):
    """Set global approval manager"""
    global _global_approval_manager
    _global_approval_manager = manager


# =============================================================================
# Approval Decorators
# =============================================================================

def requires_approval(
    operation: str,
    description: Optional[str] = None,
    approval_manager: Optional[ApprovalManager] = None,
    extract_details: Optional[Callable] = None
):
    """
    Decorator that requires approval before executing function

    Args:
        operation: Operation name
        description: Human-readable description (uses docstring if not provided)
        approval_manager: ApprovalManager instance (uses global if not provided)
        extract_details: Function to extract details from args/kwargs

    Example:
        @requires_approval(
            operation="delete_resource",
            description="Delete cloud resource",
            extract_details=lambda *args, **kwargs: {"resource_id": kwargs.get("resource_id")}
        )
        def delete_resource(resource_id: str):
            # dangerous operation
            pass
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Get approval manager
            manager = approval_manager or get_approval_manager()

            # Get description
            desc = description or func.__doc__ or f"Execute {func.__name__}"

            # Extract details
            details = {}
            if extract_details:
                try:
                    details = extract_details(*args, **kwargs)
                except Exception as e:
                    logger.warning(f"Failed to extract details: {e}")
                    details = {"error": str(e)}

            # Add function info to details
            details["function"] = func.__name__
            details["args_count"] = len(args)
            details["kwargs_count"] = len(kwargs)

            # Request approval
            decision, reason = manager.request_approval(
                operation=operation,
                description=desc,
                details=details
            )

            # Handle decision
            if decision == ApprovalDecision.APPROVED:
                # Execute function
                return func(*args, **kwargs)
            else:
                # Return error result
                error_msg = f"Operation denied: {reason}"
                logger.warning(error_msg, extra={"operation": operation})

                # Return error in same format as tool results
                return {
                    "success": False,
                    "error": error_msg,
                    "operation": operation,
                    "decision": decision.value,
                    "reason": reason
                }

        return wrapper

    return decorator


def conditional_approval(
    condition: Callable[..., bool],
    operation: str,
    description: Optional[str] = None,
    approval_manager: Optional[ApprovalManager] = None,
    extract_details: Optional[Callable] = None
):
    """
    Decorator that requires approval only if condition is met

    Args:
        condition: Function that returns True if approval is required
        operation: Operation name
        description: Human-readable description
        approval_manager: ApprovalManager instance
        extract_details: Function to extract details

    Example:
        @conditional_approval(
            condition=lambda *args, **kwargs: kwargs.get("force") is True,
            operation="delete_with_force",
            description="Delete with force flag"
        )
        def delete_item(item_id: str, force: bool = False):
            # operation
            pass
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Check condition
            if condition(*args, **kwargs):
                # Apply approval requirement
                approved_func = requires_approval(
                    operation=operation,
                    description=description,
                    approval_manager=approval_manager,
                    extract_details=extract_details
                )(func)
                return approved_func(*args, **kwargs)
            else:
                # Execute without approval
                return func(*args, **kwargs)

        return wrapper

    return decorator
