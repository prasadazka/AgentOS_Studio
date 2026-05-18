"""
Cost Estimation and Budget Guardrails for Agent_OS

Provides enterprise-grade cost controls for cloud operations:
- Cost estimation before execution
- Budget tracking and enforcement
- Resource quota management
- Cost-aware approval system
- Spend history and analytics
- Budget alerts

Supports:
- GCP (Compute Engine, Cloud Storage, BigQuery)
- AWS (coming soon)
- Azure (coming soon)
"""

import json
import time
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum
from datetime import datetime, timedelta
from pathlib import Path
from pydantic import BaseModel, Field

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.tools.approval import ApprovalManager, ApprovalMode, ApprovalDecision
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Cost Models & Pricing
# =============================================================================

class CloudProvider(str, Enum):
    """Supported cloud providers"""
    GCP = "gcp"
    AWS = "aws"
    AZURE = "azure"


class CostUnit(str, Enum):
    """Cost units"""
    USD = "usd"
    EUR = "eur"
    GBP = "gbp"


class ResourceType(str, Enum):
    """Cloud resource types"""
    # Compute
    VM_INSTANCE = "vm_instance"
    CONTAINER = "container"
    SERVERLESS_FUNCTION = "serverless_function"

    # Storage
    OBJECT_STORAGE = "object_storage"
    BLOCK_STORAGE = "block_storage"
    BACKUP_STORAGE = "backup_storage"

    # Database
    SQL_DATABASE = "sql_database"
    NOSQL_DATABASE = "nosql_database"
    DATA_WAREHOUSE = "data_warehouse"

    # Network
    DATA_TRANSFER = "data_transfer"
    LOAD_BALANCER = "load_balancer"
    VPN = "vpn"

    # Other
    API_CALL = "api_call"


# =============================================================================
# GCP Pricing (Approximate US prices as of 2024)
# =============================================================================

class GCPPricing:
    """GCP pricing estimates (US region, standard tier)"""

    # Compute Engine (per hour)
    COMPUTE_HOURLY = {
        "e2-micro": 0.01,
        "e2-small": 0.02,
        "e2-medium": 0.03,
        "e2-standard-2": 0.07,
        "e2-standard-4": 0.13,
        "e2-standard-8": 0.27,
        "n1-standard-1": 0.048,
        "n1-standard-2": 0.095,
        "n1-standard-4": 0.19,
        "n1-standard-8": 0.38,
        "n2-standard-2": 0.097,
        "n2-standard-4": 0.194,
        "n2-standard-8": 0.388,
        "n2-highmem-2": 0.130,
        "n2-highmem-4": 0.260,
        "n2-highcpu-2": 0.072,
    }

    # Cloud Storage (per GB per month)
    STORAGE_MONTHLY = {
        "STANDARD": 0.020,
        "NEARLINE": 0.010,
        "COLDLINE": 0.004,
        "ARCHIVE": 0.0012,
    }

    # BigQuery
    BIGQUERY_QUERY_PER_TB = 5.0  # $5 per TB scanned
    BIGQUERY_STORAGE_PER_GB_MONTH = 0.020  # Active storage

    # Network egress (per GB)
    NETWORK_EGRESS_PER_GB = 0.12  # First 1TB, worldwide (not China/Australia)

    # Operations
    STORAGE_OPERATIONS = {
        "class_a": 0.05 / 10000,  # Per 10k ops (write, list)
        "class_b": 0.004 / 10000,  # Per 10k ops (read)
    }

    @staticmethod
    def estimate_compute_cost(machine_type: str, hours: float) -> float:
        """Estimate Compute Engine cost"""
        hourly_rate = GCPPricing.COMPUTE_HOURLY.get(machine_type, 0.10)  # Default fallback
        return hourly_rate * hours

    @staticmethod
    def estimate_storage_cost(storage_class: str, gb: float, months: float = 1.0) -> float:
        """Estimate Cloud Storage cost"""
        monthly_rate = GCPPricing.STORAGE_MONTHLY.get(storage_class, 0.020)
        return monthly_rate * gb * months

    @staticmethod
    def estimate_bigquery_query_cost(tb_scanned: float) -> float:
        """Estimate BigQuery query cost"""
        return GCPPricing.BIGQUERY_QUERY_PER_TB * tb_scanned

    @staticmethod
    def estimate_network_egress_cost(gb: float) -> float:
        """Estimate network egress cost"""
        return GCPPricing.NETWORK_EGRESS_PER_GB * gb


# =============================================================================
# Cost Estimation Models
# =============================================================================

class CostEstimate(BaseModel):
    """Cost estimate for an operation"""
    operation: str
    resource_type: ResourceType
    estimated_cost: float
    currency: CostUnit = CostUnit.USD
    confidence: str = Field(default="medium", pattern="^(low|medium|high)$")
    breakdown: Dict[str, float] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation": self.operation,
            "resource_type": self.resource_type.value,
            "estimated_cost": round(self.estimated_cost, 4),
            "currency": self.currency.value,
            "confidence": self.confidence,
            "breakdown": {k: round(v, 4) for k, v in self.breakdown.items()},
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }


class SpendRecord(BaseModel):
    """Record of actual spending"""
    operation: str
    resource_type: ResourceType
    actual_cost: float
    estimated_cost: Optional[float] = None
    currency: CostUnit = CostUnit.USD
    approved_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation": self.operation,
            "resource_type": self.resource_type.value,
            "actual_cost": round(self.actual_cost, 4),
            "estimated_cost": round(self.estimated_cost, 4) if self.estimated_cost else None,
            "currency": self.currency.value,
            "approved_by": self.approved_by,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }


# =============================================================================
# Budget Manager
# =============================================================================

class BudgetPeriod(str, Enum):
    """Budget period types"""
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class BudgetAlert(BaseModel):
    """Budget alert configuration"""
    threshold_percent: float  # Alert when spending reaches this % of budget
    triggered: bool = False
    last_triggered: Optional[str] = None


class Budget(BaseModel):
    """Budget configuration"""
    name: str
    amount: float
    currency: CostUnit = CostUnit.USD
    period: BudgetPeriod
    start_date: str
    end_date: Optional[str] = None
    current_spend: float = 0.0
    alerts: List[BudgetAlert] = Field(default_factory=lambda: [
        BudgetAlert(threshold_percent=50.0),
        BudgetAlert(threshold_percent=80.0),
        BudgetAlert(threshold_percent=100.0)
    ])

    def remaining(self) -> float:
        """Get remaining budget"""
        return max(0.0, self.amount - self.current_spend)

    def utilization_percent(self) -> float:
        """Get budget utilization percentage"""
        if self.amount == 0:
            return 100.0
        return (self.current_spend / self.amount) * 100.0

    def is_exceeded(self) -> bool:
        """Check if budget is exceeded"""
        return self.current_spend >= self.amount

    def check_alerts(self) -> List[str]:
        """Check if any alert thresholds are triggered"""
        triggered_alerts = []
        utilization = self.utilization_percent()

        for alert in self.alerts:
            if utilization >= alert.threshold_percent and not alert.triggered:
                alert.triggered = True
                alert.last_triggered = datetime.now().isoformat()
                triggered_alerts.append(
                    f"Budget '{self.name}' alert: {utilization:.1f}% spent (threshold: {alert.threshold_percent}%)"
                )

        return triggered_alerts


class BudgetManager:
    """
    Manages budgets and spending tracking

    Features:
    - Multiple budget periods (hourly, daily, weekly, monthly, yearly)
    - Budget alerts at configurable thresholds
    - Spending history
    - Cost forecasting
    """

    def __init__(
        self,
        budgets: Optional[List[Budget]] = None,
        history_file: Optional[str] = None
    ):
        """
        Initialize budget manager

        Args:
            budgets: List of budget configurations
            history_file: Path to spend history JSON file
        """
        self.budgets = budgets or []
        self.history_file = history_file
        self.spend_history: List[SpendRecord] = []

        # Load history if file exists
        if history_file and Path(history_file).exists():
            self._load_history()

    def add_budget(self, budget: Budget):
        """Add a budget"""
        self.budgets.append(budget)

    def record_spend(self, spend_record: SpendRecord):
        """Record spending"""
        self.spend_history.append(spend_record)

        # Update budget spend
        for budget in self.budgets:
            if self._is_in_budget_period(spend_record.timestamp, budget):
                budget.current_spend += spend_record.actual_cost

                # Check alerts
                alerts = budget.check_alerts()
                for alert_msg in alerts:
                    logger.warning(alert_msg)

        # Save to file
        if self.history_file:
            self._save_history()

    def check_budget_available(self, estimated_cost: float) -> Tuple[bool, str]:
        """
        Check if estimated cost fits within active budgets

        Returns:
            (can_proceed, reason)
        """
        now = datetime.now().isoformat()

        for budget in self.budgets:
            if self._is_in_budget_period(now, budget):
                if budget.current_spend + estimated_cost > budget.amount:
                    return False, f"Exceeds {budget.period.value} budget '{budget.name}' (${budget.remaining():.2f} remaining)"

        return True, "Within budget"

    def get_spend_summary(self, period: BudgetPeriod = BudgetPeriod.MONTHLY) -> Dict[str, Any]:
        """Get spending summary for period"""
        # Filter records in period
        period_records = [
            r for r in self.spend_history
            if self._is_in_current_period(r.timestamp, period)
        ]

        total_spend = sum(r.actual_cost for r in period_records)

        # Group by resource type
        by_resource = {}
        for record in period_records:
            resource = record.resource_type.value
            by_resource[resource] = by_resource.get(resource, 0.0) + record.actual_cost

        return {
            "period": period.value,
            "total_spend": round(total_spend, 2),
            "record_count": len(period_records),
            "by_resource_type": {k: round(v, 2) for k, v in by_resource.items()},
            "currency": "usd"
        }

    def _is_in_budget_period(self, timestamp: str, budget: Budget) -> bool:
        """Check if timestamp falls within budget period"""
        ts = datetime.fromisoformat(timestamp)
        start = datetime.fromisoformat(budget.start_date)

        if budget.end_date:
            end = datetime.fromisoformat(budget.end_date)
            return start <= ts <= end

        # Check if in current period
        now = datetime.now()

        if budget.period == BudgetPeriod.HOURLY:
            return ts.date() == now.date() and ts.hour == now.hour
        elif budget.period == BudgetPeriod.DAILY:
            return ts.date() == now.date()
        elif budget.period == BudgetPeriod.WEEKLY:
            return ts.isocalendar()[1] == now.isocalendar()[1]
        elif budget.period == BudgetPeriod.MONTHLY:
            return ts.year == now.year and ts.month == now.month
        elif budget.period == BudgetPeriod.YEARLY:
            return ts.year == now.year

        return False

    def _is_in_current_period(self, timestamp: str, period: BudgetPeriod) -> bool:
        """Check if timestamp is in current period"""
        ts = datetime.fromisoformat(timestamp)
        now = datetime.now()

        if period == BudgetPeriod.HOURLY:
            return ts >= now - timedelta(hours=1)
        elif period == BudgetPeriod.DAILY:
            return ts.date() == now.date()
        elif period == BudgetPeriod.WEEKLY:
            return ts >= now - timedelta(days=7)
        elif period == BudgetPeriod.MONTHLY:
            return ts.year == now.year and ts.month == now.month
        elif period == BudgetPeriod.YEARLY:
            return ts.year == now.year

        return False

    def _save_history(self):
        """Save spend history to file"""
        try:
            history_data = [r.to_dict() for r in self.spend_history[-1000:]]  # Keep last 1000 records
            with open(self.history_file, 'w') as f:
                json.dump(history_data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save spend history: {e}")

    def _load_history(self):
        """Load spend history from file"""
        try:
            with open(self.history_file, 'r') as f:
                history_data = json.load(f)
                self.spend_history = [
                    SpendRecord(
                        operation=r["operation"],
                        resource_type=ResourceType(r["resource_type"]),
                        actual_cost=r["actual_cost"],
                        estimated_cost=r.get("estimated_cost"),
                        currency=CostUnit(r.get("currency", "usd")),
                        approved_by=r.get("approved_by"),
                        metadata=r.get("metadata", {}),
                        timestamp=r["timestamp"]
                    )
                    for r in history_data
                ]
        except Exception as e:
            logger.warning(f"Failed to load spend history: {e}")


# =============================================================================
# Cost-Aware Approval System
# =============================================================================

class CostAwareApprovalManager(ApprovalManager):
    """
    Approval manager that considers cost in approval decisions

    Features:
    - Automatic approval below cost threshold
    - Require approval above cost threshold
    - Budget-aware approval
    - Cost tracking
    """

    def __init__(
        self,
        mode: ApprovalMode = ApprovalMode.INTERACTIVE,
        auto_approve_threshold: float = 1.0,  # Auto-approve below $1
        budget_manager: Optional[BudgetManager] = None,
        **kwargs
    ):
        """
        Initialize cost-aware approval manager

        Args:
            mode: Base approval mode
            auto_approve_threshold: Auto-approve operations below this cost
            budget_manager: Budget manager instance
        """
        super().__init__(mode=mode, **kwargs)
        self.auto_approve_threshold = auto_approve_threshold
        self.budget_manager = budget_manager

    def request_approval_with_cost(
        self,
        operation: str,
        description: str,
        cost_estimate: CostEstimate,
        details: Optional[Dict[str, Any]] = None,
        timeout: int = 60
    ) -> Tuple[ApprovalDecision, Optional[str]]:
        """
        Request approval with cost consideration

        Args:
            operation: Operation name
            description: Description
            cost_estimate: Cost estimate for operation
            details: Additional details
            timeout: Approval timeout

        Returns:
            (decision, reason)
        """
        details = details or {}
        details["estimated_cost"] = cost_estimate.estimated_cost
        details["cost_breakdown"] = cost_estimate.breakdown
        details["currency"] = cost_estimate.currency.value

        # Check budget first
        if self.budget_manager:
            can_proceed, budget_reason = self.budget_manager.check_budget_available(
                cost_estimate.estimated_cost
            )
            if not can_proceed:
                return ApprovalDecision.DENIED, f"Budget exceeded: {budget_reason}"

        # Auto-approve if below threshold
        if cost_estimate.estimated_cost < self.auto_approve_threshold:
            decision = ApprovalDecision.APPROVED
            reason = f"Auto-approved: cost ${cost_estimate.estimated_cost:.2f} below threshold ${self.auto_approve_threshold:.2f}"
            self._record_decision(operation, description, decision, reason, details)
            return decision, reason

        # Otherwise, use standard approval flow
        enhanced_description = f"{description} (Estimated cost: ${cost_estimate.estimated_cost:.2f})"
        return self.request_approval(operation, enhanced_description, details, timeout)


# =============================================================================
# Cost Estimation Tool
# =============================================================================

class CostEstimatorTool(BaseTool):
    """
    Estimate costs for cloud operations

    Supports:
    - GCP Compute Engine
    - GCP Cloud Storage
    - GCP BigQuery
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="cost_estimator",
            description="Estimate costs for cloud operations before execution",
            category="cloud",
            version="1.0.0",
            requires_auth=False
        )
        super().__init__(metadata)

    def _execute(
        self,
        provider: str,
        operation: str,
        **params
    ) -> str:
        """
        Estimate operation cost

        Args:
            provider: Cloud provider (gcp, aws, azure)
            operation: Operation type (create_vm, query_bigquery, upload_storage, etc.)
            **params: Operation-specific parameters

        Returns:
            JSON cost estimate
        """
        if provider == "gcp":
            return self._estimate_gcp(operation, **params)
        elif provider == "aws":
            return json.dumps({"error": "AWS pricing not yet implemented"})
        elif provider == "azure":
            return json.dumps({"error": "Azure pricing not yet implemented"})
        else:
            return json.dumps({"error": f"Unknown provider: {provider}"})

    def _estimate_gcp(self, operation: str, **params) -> str:
        """Estimate GCP operation cost"""

        # Compute Engine
        if operation == "create_vm" or operation == "vm_runtime":
            machine_type = params.get("machine_type", "e2-medium")
            hours = params.get("hours", 1.0)
            cost = GCPPricing.estimate_compute_cost(machine_type, hours)

            estimate = CostEstimate(
                operation=operation,
                resource_type=ResourceType.VM_INSTANCE,
                estimated_cost=cost,
                confidence="high",
                breakdown={"compute": cost},
                metadata={"machine_type": machine_type, "hours": hours}
            )
            return json.dumps(estimate.to_dict(), indent=2)

        # Cloud Storage
        elif operation == "storage":
            storage_class = params.get("storage_class", "STANDARD")
            gb = params.get("gb", 0.0)
            months = params.get("months", 1.0)
            cost = GCPPricing.estimate_storage_cost(storage_class, gb, months)

            estimate = CostEstimate(
                operation=operation,
                resource_type=ResourceType.OBJECT_STORAGE,
                estimated_cost=cost,
                confidence="high",
                breakdown={"storage": cost},
                metadata={"storage_class": storage_class, "gb": gb, "months": months}
            )
            return json.dumps(estimate.to_dict(), indent=2)

        # BigQuery
        elif operation == "bigquery_query":
            tb_scanned = params.get("tb_scanned", 0.001)  # Default 1GB
            cost = GCPPricing.estimate_bigquery_query_cost(tb_scanned)

            estimate = CostEstimate(
                operation=operation,
                resource_type=ResourceType.DATA_WAREHOUSE,
                estimated_cost=cost,
                confidence="medium",
                breakdown={"query": cost},
                metadata={"tb_scanned": tb_scanned}
            )
            return json.dumps(estimate.to_dict(), indent=2)

        else:
            return json.dumps({"error": f"Unknown GCP operation: {operation}"})


# =============================================================================
# Global Budget Manager
# =============================================================================

_global_budget_manager: Optional[BudgetManager] = None


def get_budget_manager() -> BudgetManager:
    """Get global budget manager (creates if not exists)"""
    global _global_budget_manager
    if _global_budget_manager is None:
        _global_budget_manager = BudgetManager()
    return _global_budget_manager


def set_budget_manager(manager: BudgetManager):
    """Set global budget manager"""
    global _global_budget_manager
    _global_budget_manager = manager
