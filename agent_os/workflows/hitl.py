"""
Human-in-the-Loop (HITL) Workflow Nodes

Allows workflows to pause for human input, approval, or decision-making.
Essential for critical operations requiring human oversight.
"""

from typing import Dict, Any, Optional, Callable, List
from pydantic import BaseModel, Field
from enum import Enum
import time
from datetime import datetime

from agent_os.utils.logging import get_logger

logger = get_logger("workflows.hitl")


class ApprovalStatus(str, Enum):
    """Status of human approval"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


class HITLRequest(BaseModel):
    """Request for human input/approval"""
    request_id: str = Field(..., description="Unique request ID")
    request_type: str = Field(..., description="Type: 'approval', 'input', 'choice'")
    prompt: str = Field(..., description="Prompt for human")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context")
    options: Optional[List[str]] = Field(None, description="Options for choice type")
    default_value: Optional[Any] = Field(None, description="Default if timeout")
    timeout_seconds: Optional[float] = Field(None, description="Timeout in seconds")
    created_at: datetime = Field(default_factory=datetime.now)


class HITLResponse(BaseModel):
    """Human response to HITL request"""
    request_id: str
    status: ApprovalStatus
    value: Optional[Any] = None
    comment: Optional[str] = None
    responded_at: datetime = Field(default_factory=datetime.now)


class HITLManager:
    """
    Manages human-in-the-loop requests and responses.

    Supports multiple interaction modes:
    - Approval: Binary approve/reject decisions
    - Input: Free-form text input
    - Choice: Select from predefined options

    Thread-safe for concurrent workflows.
    """

    def __init__(
        self,
        default_timeout: float = 300.0,  # 5 minutes
        input_handler: Optional[Callable] = None
    ):
        """
        Initialize HITL manager

        Args:
            default_timeout: Default timeout for requests (seconds)
            input_handler: Custom handler for getting human input
                          (defaults to console input)
        """
        self.default_timeout = default_timeout
        self.input_handler = input_handler or self._console_input_handler

        # Store pending and completed requests
        self._pending_requests: Dict[str, HITLRequest] = {}
        self._responses: Dict[str, HITLResponse] = {}

        logger.info(f"HITL Manager initialized (timeout={default_timeout}s)")

    def _console_input_handler(self, request: HITLRequest) -> HITLResponse:
        """
        Default console-based input handler

        Args:
            request: HITL request

        Returns:
            Human response
        """
        print("\n" + "="*70)
        print("🤚 HUMAN INPUT REQUIRED")
        print("="*70)
        print(f"Request ID: {request.request_id}")
        print(f"Type: {request.request_type}")
        print(f"\n{request.prompt}\n")

        if request.context:
            print("Context:")
            for key, value in request.context.items():
                value_str = str(value)[:200]
                print(f"  {key}: {value_str}")
            print()

        # Handle different request types
        if request.request_type == "approval":
            return self._handle_approval(request)
        elif request.request_type == "input":
            return self._handle_input(request)
        elif request.request_type == "choice":
            return self._handle_choice(request)
        else:
            raise ValueError(f"Unknown request type: {request.request_type}")

    def _handle_approval(self, request: HITLRequest) -> HITLResponse:
        """Handle approval request"""
        while True:
            response = input("Approve? (yes/no): ").strip().lower()

            if response in ['yes', 'y']:
                comment = input("Optional comment: ").strip()
                return HITLResponse(
                    request_id=request.request_id,
                    status=ApprovalStatus.APPROVED,
                    value=True,
                    comment=comment if comment else None
                )
            elif response in ['no', 'n']:
                comment = input("Reason for rejection: ").strip()
                return HITLResponse(
                    request_id=request.request_id,
                    status=ApprovalStatus.REJECTED,
                    value=False,
                    comment=comment if comment else "Rejected by human"
                )
            else:
                print("Invalid input. Please enter 'yes' or 'no'.")

    def _handle_input(self, request: HITLRequest) -> HITLResponse:
        """Handle free-form input request"""
        value = input("Your input: ").strip()

        if not value and request.default_value is not None:
            value = request.default_value
            print(f"Using default: {value}")

        return HITLResponse(
            request_id=request.request_id,
            status=ApprovalStatus.APPROVED,
            value=value
        )

    def _handle_choice(self, request: HITLRequest) -> HITLResponse:
        """Handle multiple choice request"""
        if not request.options:
            raise ValueError("Choice request must have options")

        print("Options:")
        for i, option in enumerate(request.options, 1):
            print(f"  {i}. {option}")
        print()

        while True:
            try:
                choice = input(f"Choose (1-{len(request.options)}): ").strip()
                idx = int(choice) - 1

                if 0 <= idx < len(request.options):
                    selected = request.options[idx]
                    return HITLResponse(
                        request_id=request.request_id,
                        status=ApprovalStatus.APPROVED,
                        value=selected
                    )
                else:
                    print(f"Invalid choice. Enter 1-{len(request.options)}")
            except ValueError:
                print("Invalid input. Enter a number.")

    def request_approval(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        request_id: Optional[str] = None
    ) -> HITLResponse:
        """
        Request human approval

        Args:
            prompt: Approval prompt
            context: Additional context
            timeout: Timeout in seconds (None = default)
            request_id: Custom request ID (auto-generated if None)

        Returns:
            Human response with approval status
        """
        request_id = request_id or f"approval_{int(time.time())}"
        timeout = timeout if timeout is not None else self.default_timeout

        request = HITLRequest(
            request_id=request_id,
            request_type="approval",
            prompt=prompt,
            context=context or {},
            timeout_seconds=timeout
        )

        self._pending_requests[request_id] = request

        try:
            # Get human response with timeout
            start_time = time.time()

            response = self.input_handler(request)

            elapsed = time.time() - start_time

            # Check timeout
            if timeout and elapsed > timeout:
                logger.warning(f"Request {request_id} timed out after {elapsed:.1f}s")
                response.status = ApprovalStatus.TIMEOUT

            # Store response
            self._responses[request_id] = response
            del self._pending_requests[request_id]

            logger.info(
                f"Approval request {request_id}: {response.status} "
                f"(elapsed={elapsed:.1f}s)"
            )

            return response

        except Exception as e:
            logger.error(f"Error in approval request {request_id}: {e}")
            response = HITLResponse(
                request_id=request_id,
                status=ApprovalStatus.REJECTED,
                comment=f"Error: {str(e)}"
            )
            self._responses[request_id] = response
            return response

    def request_input(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        default_value: Optional[str] = None,
        timeout: Optional[float] = None,
        request_id: Optional[str] = None
    ) -> HITLResponse:
        """
        Request human text input

        Args:
            prompt: Input prompt
            context: Additional context
            default_value: Default value if timeout
            timeout: Timeout in seconds
            request_id: Custom request ID

        Returns:
            Human response with input value
        """
        request_id = request_id or f"input_{int(time.time())}"
        timeout = timeout if timeout is not None else self.default_timeout

        request = HITLRequest(
            request_id=request_id,
            request_type="input",
            prompt=prompt,
            context=context or {},
            default_value=default_value,
            timeout_seconds=timeout
        )

        self._pending_requests[request_id] = request

        try:
            response = self.input_handler(request)
            self._responses[request_id] = response
            del self._pending_requests[request_id]

            logger.info(f"Input request {request_id} completed")
            return response

        except Exception as e:
            logger.error(f"Error in input request {request_id}: {e}")
            response = HITLResponse(
                request_id=request_id,
                status=ApprovalStatus.REJECTED,
                comment=f"Error: {str(e)}",
                value=default_value
            )
            self._responses[request_id] = response
            return response

    def request_choice(
        self,
        prompt: str,
        options: List[str],
        context: Optional[Dict[str, Any]] = None,
        default_index: Optional[int] = None,
        timeout: Optional[float] = None,
        request_id: Optional[str] = None
    ) -> HITLResponse:
        """
        Request human to choose from options

        Args:
            prompt: Choice prompt
            options: List of options
            context: Additional context
            default_index: Default option index if timeout
            timeout: Timeout in seconds
            request_id: Custom request ID

        Returns:
            Human response with selected option
        """
        if not options:
            raise ValueError("Must provide at least one option")

        request_id = request_id or f"choice_{int(time.time())}"
        timeout = timeout if timeout is not None else self.default_timeout

        default_value = options[default_index] if default_index is not None else None

        request = HITLRequest(
            request_id=request_id,
            request_type="choice",
            prompt=prompt,
            context=context or {},
            options=options,
            default_value=default_value,
            timeout_seconds=timeout
        )

        self._pending_requests[request_id] = request

        try:
            response = self.input_handler(request)
            self._responses[request_id] = response
            del self._pending_requests[request_id]

            logger.info(f"Choice request {request_id}: {response.value}")
            return response

        except Exception as e:
            logger.error(f"Error in choice request {request_id}: {e}")
            response = HITLResponse(
                request_id=request_id,
                status=ApprovalStatus.REJECTED,
                comment=f"Error: {str(e)}",
                value=default_value
            )
            self._responses[request_id] = response
            return response

    def get_response(self, request_id: str) -> Optional[HITLResponse]:
        """Get response for a request ID"""
        return self._responses.get(request_id)

    def get_pending_count(self) -> int:
        """Get number of pending requests"""
        return len(self._pending_requests)

    def clear_history(self):
        """Clear response history (keeps pending requests)"""
        self._responses.clear()
        logger.debug("Cleared HITL response history")


# Global HITL manager instance
_hitl_manager: Optional[HITLManager] = None


def get_hitl_manager() -> HITLManager:
    """Get global HITL manager instance"""
    global _hitl_manager
    if _hitl_manager is None:
        _hitl_manager = HITLManager()
    return _hitl_manager


def create_approval_node(
    prompt: str,
    context_key: Optional[str] = None,
    timeout: float = 300.0
) -> Callable:
    """
    Create a workflow node that requires human approval

    Args:
        prompt: Approval prompt
        context_key: State key to include as context
        timeout: Timeout in seconds

    Returns:
        Node function for workflow

    Example:
        approval_node = create_approval_node(
            prompt="Approve deployment to production?",
            context_key="deployment_plan",
            timeout=600.0
        )
    """
    hitl_manager = get_hitl_manager()

    def approval_node(state: Dict[str, Any]) -> Dict[str, Any]:
        """Approval node function"""
        context = {}
        if context_key and context_key in state:
            context[context_key] = state[context_key]

        response = hitl_manager.request_approval(
            prompt=prompt,
            context=context,
            timeout=timeout
        )

        # Update state
        state["hitl_response"] = response.model_dump()
        state["hitl_approved"] = (response.status == ApprovalStatus.APPROVED)

        if response.status == ApprovalStatus.REJECTED:
            state["error"] = f"Rejected: {response.comment}"

        return state

    return approval_node


def create_input_node(
    prompt: str,
    output_key: str = "human_input",
    default_value: Optional[str] = None,
    timeout: float = 300.0
) -> Callable:
    """
    Create a workflow node that requests human input

    Args:
        prompt: Input prompt
        output_key: State key to store input
        default_value: Default value if timeout
        timeout: Timeout in seconds

    Returns:
        Node function for workflow
    """
    hitl_manager = get_hitl_manager()

    def input_node(state: Dict[str, Any]) -> Dict[str, Any]:
        """Input node function"""
        response = hitl_manager.request_input(
            prompt=prompt,
            context=state,
            default_value=default_value,
            timeout=timeout
        )

        # Store input in state
        state[output_key] = response.value
        state["hitl_response"] = response.model_dump()

        return state

    return input_node
