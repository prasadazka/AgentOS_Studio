"""
Cost Tracking and Budget Management for Agent_OS

Tracks costs over time and enforces budget limits.
Essential for production deployments with cost constraints.

Features:
- Per-agent cost tracking
- Time-windowed aggregation (hourly, daily, monthly)
- Budget enforcement with warnings
- Cost analytics and reporting
"""

import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import RLock
from collections import defaultdict, deque

from agent_os.utils.logging import get_logger
from agent_os.utils.token_counter import TokenUsage, CostSummary

logger = get_logger(__name__)


# =============================================================================
# Budget Configuration
# =============================================================================

@dataclass
class Budget:
    """Budget configuration"""
    limit: float  # Budget limit in USD
    window: str  # Time window: 'hourly', 'daily', 'monthly', 'total'
    warning_threshold: float = 0.8  # Warn at 80% of budget
    hard_limit: bool = True  # Block calls when budget exceeded

    def __post_init__(self):
        if self.window not in ['hourly', 'daily', 'monthly', 'total']:
            raise ValueError(f"Invalid window: {self.window}. Must be 'hourly', 'daily', 'monthly', or 'total'")


class BudgetExceededError(Exception):
    """Raised when budget limit is exceeded"""
    pass


# =============================================================================
# Cost Tracker
# =============================================================================

class CostTracker:
    """
    Track costs per agent with budget enforcement

    Features:
    - Accumulates token usage and costs
    - Time-windowed cost tracking
    - Budget warnings and enforcement
    - Cost analytics

    Example:
        tracker = CostTracker(
            agent_name="MyAgent",
            budget=Budget(limit=10.0, window='daily')
        )

        tracker.record_usage(token_usage)

        if tracker.is_budget_exceeded():
            print("Budget exceeded!")
    """

    def __init__(
        self,
        agent_name: str,
        model: str,
        budget: Optional[Budget] = None
    ):
        """
        Initialize cost tracker

        Args:
            agent_name: Name of the agent
            model: Model being used
            budget: Optional budget configuration
        """
        self.agent_name = agent_name
        self.model = model
        self.budget = budget

        # Usage history (bounded circular buffer to prevent memory leaks)
        # Max 10,000 entries (~2MB memory) - older entries automatically evicted
        self._usage_history: deque = deque(maxlen=10_000)
        self._lock = RLock()

        # Aggregated metrics
        self._total_calls = 0
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cost = 0.0
        self._start_time = datetime.now()

        # Time-bucketed cost aggregation (O(1) lookup for window costs)
        # Format: "2026-01-28-14" for hourly, "2026-01-28" for daily, "2026-01" for monthly
        self._hourly_costs: Dict[str, float] = {}
        self._daily_costs: Dict[str, float] = {}
        self._monthly_costs: Dict[str, float] = {}

        # Budget warnings
        self._warning_triggered = False

        logger.info(
            f"Cost tracker initialized for agent '{agent_name}' with model '{model}' "
            f"(history limit: {self._usage_history.maxlen} entries)"
        )
        if budget:
            logger.info(f"Budget: ${budget.limit} per {budget.window}")

    def record_usage(self, usage: TokenUsage):
        """
        Record token usage

        Args:
            usage: TokenUsage object

        Raises:
            BudgetExceededError: If budget is exceeded and hard_limit is True
        """
        with self._lock:
            # Check budget before recording
            if self.budget and self.budget.hard_limit:
                if self._check_budget_exceeded():
                    current_cost = self.get_current_window_cost()
                    raise BudgetExceededError(
                        f"Budget exceeded for agent '{self.agent_name}': "
                        f"${current_cost:.4f} / ${self.budget.limit:.2f} ({self.budget.window})"
                    )

            # Record usage
            self._usage_history.append(usage)
            self._total_calls += 1
            self._total_input_tokens += usage.input_tokens
            self._total_output_tokens += usage.output_tokens

            cost = usage.calculate_cost()
            self._total_cost += cost

            # Update time-bucketed costs for O(1) window lookups
            timestamp = usage.timestamp
            hour_key = timestamp.strftime("%Y-%m-%d-%H")
            day_key = timestamp.strftime("%Y-%m-%d")
            month_key = timestamp.strftime("%Y-%m")

            self._hourly_costs[hour_key] = self._hourly_costs.get(hour_key, 0.0) + cost
            self._daily_costs[day_key] = self._daily_costs.get(day_key, 0.0) + cost
            self._monthly_costs[month_key] = self._monthly_costs.get(month_key, 0.0) + cost

            # Periodic cleanup of old time buckets (every 1000 calls)
            if self._total_calls % 1000 == 0:
                self._cleanup_old_time_buckets()

            # Check for warning threshold
            if self.budget and not self._warning_triggered:
                usage_ratio = self.get_budget_usage_ratio()
                if usage_ratio >= self.budget.warning_threshold:
                    self._warning_triggered = True
                    current_cost = self.get_current_window_cost()
                    logger.warning(
                        f"Budget warning for agent '{self.agent_name}': "
                        f"{usage_ratio*100:.1f}% used (${current_cost:.4f} / ${self.budget.limit:.2f})"
                    )

    def get_current_window_cost(self) -> float:
        """
        Get cost for current budget window (O(1) lookup)

        Returns:
            Cost in USD for current window
        """
        if not self.budget or self.budget.window == 'total':
            return self._total_cost

        now = datetime.now()
        window = self.budget.window

        with self._lock:
            # O(1) lookup using time-bucketed aggregation
            if window == 'hourly':
                hour_key = now.strftime("%Y-%m-%d-%H")
                return self._hourly_costs.get(hour_key, 0.0)
            elif window == 'daily':
                day_key = now.strftime("%Y-%m-%d")
                return self._daily_costs.get(day_key, 0.0)
            elif window == 'monthly':
                month_key = now.strftime("%Y-%m")
                return self._monthly_costs.get(month_key, 0.0)
            else:
                # Fallback to total (should not reach here)
                return self._total_cost

    def _cleanup_old_time_buckets(self):
        """
        Clean up old time buckets to prevent unbounded memory growth

        Keeps:
        - Last 48 hours of hourly data
        - Last 90 days of daily data
        - Last 24 months of monthly data
        """
        now = datetime.now()

        # Cleanup hourly buckets (keep last 48 hours)
        cutoff_hour = (now - timedelta(hours=48)).strftime("%Y-%m-%d-%H")
        self._hourly_costs = {
            k: v for k, v in self._hourly_costs.items()
            if k >= cutoff_hour
        }

        # Cleanup daily buckets (keep last 90 days)
        cutoff_day = (now - timedelta(days=90)).strftime("%Y-%m-%d")
        self._daily_costs = {
            k: v for k, v in self._daily_costs.items()
            if k >= cutoff_day
        }

        # Cleanup monthly buckets (keep last 24 months)
        cutoff_month = (now - timedelta(days=730)).strftime("%Y-%m")
        self._monthly_costs = {
            k: v for k, v in self._monthly_costs.items()
            if k >= cutoff_month
        }

    def _get_window_start(self, now: datetime, window: str) -> datetime:
        """Calculate start of current time window"""
        if window == 'hourly':
            return now.replace(minute=0, second=0, microsecond=0)
        elif window == 'daily':
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif window == 'monthly':
            return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:  # total
            return self._start_time

    def _check_budget_exceeded(self) -> bool:
        """Check if budget is exceeded"""
        if not self.budget:
            return False

        current_cost = self.get_current_window_cost()
        return current_cost >= self.budget.limit

    def is_budget_exceeded(self) -> bool:
        """Check if budget is exceeded (public method)"""
        with self._lock:
            return self._check_budget_exceeded()

    def get_budget_usage_ratio(self) -> float:
        """Get budget usage as ratio (0.0 to 1.0+)"""
        if not self.budget:
            return 0.0

        current_cost = self.get_current_window_cost()
        return current_cost / self.budget.limit if self.budget.limit > 0 else 0.0

    def get_remaining_budget(self) -> Optional[float]:
        """Get remaining budget in USD"""
        if not self.budget:
            return None

        current_cost = self.get_current_window_cost()
        return max(0.0, self.budget.limit - current_cost)

    def get_summary(self) -> CostSummary:
        """Get cost summary"""
        with self._lock:
            return CostSummary(
                total_calls=self._total_calls,
                total_input_tokens=self._total_input_tokens,
                total_output_tokens=self._total_output_tokens,
                total_tokens=self._total_input_tokens + self._total_output_tokens,
                total_cost=self._total_cost,
                model=self.model,
                start_time=self._start_time,
                end_time=datetime.now()
            )

    def get_metrics(self) -> Dict[str, Any]:
        """Get detailed metrics"""
        summary = self.get_summary()
        metrics = summary.to_dict()

        # Add budget info
        if self.budget:
            metrics["budget"] = {
                "limit": self.budget.limit,
                "window": self.budget.window,
                "current_usage": self.get_current_window_cost(),
                "remaining": self.get_remaining_budget(),
                "usage_ratio": self.get_budget_usage_ratio(),
                "exceeded": self.is_budget_exceeded()
            }

        return metrics

    def reset_warning(self):
        """Reset budget warning flag"""
        with self._lock:
            self._warning_triggered = False

    def get_usage_history(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> List[TokenUsage]:
        """
        Get usage history filtered by time range

        Args:
            start_time: Filter start time
            end_time: Filter end time
            limit: Maximum number of records to return

        Returns:
            List of TokenUsage objects
        """
        with self._lock:
            history = self._usage_history.copy()

        # Filter by time
        if start_time:
            history = [u for u in history if u.timestamp >= start_time]
        if end_time:
            history = [u for u in history if u.timestamp <= end_time]

        # Limit results
        if limit:
            history = history[-limit:]

        return history


# =============================================================================
# Global Cost Tracker Manager
# =============================================================================

class CostTrackerManager:
    """
    Manage cost trackers for multiple agents

    Features:
    - Centralized tracking across all agents
    - Aggregated cost reporting
    - System-wide budget monitoring
    - LRU-based cleanup to prevent memory leaks
    """

    def __init__(self, max_trackers: int = 1000):
        """
        Initialize manager

        Args:
            max_trackers: Maximum number of cost trackers to maintain.
                         Older trackers automatically evicted via LRU when exceeded.
        """
        self._trackers: Dict[str, CostTracker] = {}
        self._access_times: Dict[str, float] = {}  # Track last access time for LRU
        self._max_trackers = max_trackers
        self._lock = RLock()

        logger.info(
            f"Cost tracker manager initialized (max_trackers: {max_trackers})"
        )

    def _cleanup_old_trackers(self):
        """
        Remove least recently used cost trackers when limit exceeded

        This prevents memory leaks in multi-tenant or dynamic agent scenarios
        where trackers are created per-user or per-session.
        """
        if len(self._trackers) <= self._max_trackers:
            return

        # Remove oldest 10% of trackers
        num_to_remove = max(1, int(self._max_trackers * 0.1))

        # Sort by access time (oldest first)
        sorted_trackers = sorted(
            self._access_times.items(),
            key=lambda x: x[1]
        )

        # Remove oldest trackers
        for key, _ in sorted_trackers[:num_to_remove]:
            if key in self._trackers:
                del self._trackers[key]
                del self._access_times[key]
                logger.info(
                    f"Evicted cost tracker '{key}' (LRU cleanup, "
                    f"total: {len(self._trackers)})"
                )

    def get_or_create(
        self,
        agent_name: str,
        model: str,
        budget: Optional[Budget] = None
    ) -> CostTracker:
        """
        Get existing or create new cost tracker

        Args:
            agent_name: Agent name
            model: Model name
            budget: Optional budget

        Returns:
            CostTracker instance
        """
        with self._lock:
            key = f"{agent_name}_{model}"

            # Update access time
            self._access_times[key] = time.time()

            if key not in self._trackers:
                # Cleanup old trackers if needed
                self._cleanup_old_trackers()

                self._trackers[key] = CostTracker(
                    agent_name=agent_name,
                    model=model,
                    budget=budget
                )

            return self._trackers[key]

    def get_tracker(self, agent_name: str, model: str) -> Optional[CostTracker]:
        """Get existing tracker"""
        with self._lock:
            key = f"{agent_name}_{model}"
            if key in self._trackers:
                # Update access time for LRU
                self._access_times[key] = time.time()
            return self._trackers.get(key)

    def get_all_trackers(self) -> Dict[str, CostTracker]:
        """Get all trackers"""
        with self._lock:
            return self._trackers.copy()

    def get_total_cost(self) -> float:
        """Get total cost across all agents"""
        with self._lock:
            return sum(tracker._total_cost for tracker in self._trackers.values())

    def get_total_tokens(self) -> int:
        """Get total tokens across all agents"""
        with self._lock:
            return sum(
                tracker._total_input_tokens + tracker._total_output_tokens
                for tracker in self._trackers.values()
            )

    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all agents"""
        with self._lock:
            return {
                name: tracker.get_metrics()
                for name, tracker in self._trackers.items()
            }

    def get_cost_breakdown(self) -> Dict[str, Any]:
        """Get cost breakdown by agent and model"""
        with self._lock:
            breakdown = {
                "total_cost": self.get_total_cost(),
                "total_tokens": self.get_total_tokens(),
                "by_agent": {},
                "by_model": defaultdict(lambda: {"cost": 0.0, "tokens": 0})
            }

            for name, tracker in self._trackers.items():
                # Per-agent breakdown
                breakdown["by_agent"][name] = {
                    "cost": tracker._total_cost,
                    "tokens": tracker._total_input_tokens + tracker._total_output_tokens,
                    "calls": tracker._total_calls
                }

                # Per-model breakdown
                model = tracker.model
                breakdown["by_model"][model]["cost"] += tracker._total_cost
                breakdown["by_model"][model]["tokens"] += (
                    tracker._total_input_tokens + tracker._total_output_tokens
                )

            # Convert defaultdict to regular dict
            breakdown["by_model"] = dict(breakdown["by_model"])

            return breakdown

    def get_agents_over_budget(self) -> List[str]:
        """Get list of agents that have exceeded their budget"""
        with self._lock:
            return [
                name for name, tracker in self._trackers.items()
                if tracker.is_budget_exceeded()
            ]


# Singleton instance
_cost_tracker_manager: Optional[CostTrackerManager] = None


def get_cost_tracker_manager() -> CostTrackerManager:
    """Get global cost tracker manager instance"""
    global _cost_tracker_manager
    if _cost_tracker_manager is None:
        _cost_tracker_manager = CostTrackerManager()
    return _cost_tracker_manager
