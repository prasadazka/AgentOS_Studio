"""
Performance Metrics Collection for Agent_OS

Provides comprehensive performance monitoring and observability.
Essential for production deployments to track system health and SLAs.

Features:
- Latency tracking (P50, P95, P99 percentiles)
- Throughput metrics (requests/sec)
- Error rate monitoring
- Per-agent and system-wide metrics
- Thread-safe metric collection

Metrics Collected:
- Request latency (execution time)
- Success/failure rates
- Token usage per request
- Cost per request
- Throughput (requests per second)
"""

import time
import threading
from typing import Dict, List, Any, Optional
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class MetricDataPoint:
    """Single metric data point"""
    timestamp: datetime
    latency_ms: float
    success: bool
    error_type: Optional[str] = None
    tokens_used: int = 0
    cost: float = 0.0


@dataclass
class PerformanceMetrics:
    """Aggregated performance metrics"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0

    # Latency metrics (milliseconds)
    avg_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0

    # Throughput
    requests_per_second: float = 0.0

    # Error rate
    error_rate: float = 0.0
    errors_by_type: Dict[str, int] = field(default_factory=dict)

    # Resource usage
    total_tokens: int = 0
    total_cost: float = 0.0
    avg_tokens_per_request: float = 0.0
    avg_cost_per_request: float = 0.0

    # Time window
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None


class MetricsCollector:
    """
    Collect and aggregate performance metrics

    Thread-safe metrics collection with sliding window.
    Automatically calculates percentiles and aggregates.

    Example:
        collector = MetricsCollector(name="my_agent")

        start = time.time()
        result = execute_operation()
        latency = (time.time() - start) * 1000  # ms

        collector.record_request(
            latency_ms=latency,
            success=True,
            tokens_used=150,
            cost=0.003
        )

        metrics = collector.get_metrics()
    """

    def __init__(
        self,
        name: str,
        window_size: int = 10_000,
        enable_detailed_tracking: bool = True
    ):
        """
        Initialize metrics collector

        Args:
            name: Collector name (usually agent name)
            window_size: Max data points to keep (sliding window)
            enable_detailed_tracking: Track detailed per-request metrics
        """
        self.name = name
        self.window_size = window_size
        self.enable_detailed_tracking = enable_detailed_tracking

        # Sliding window of data points (bounded)
        self._data_points: deque = deque(maxlen=window_size)
        self._lock = threading.RLock()

        # Running counters (fast access)
        self._total_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0
        self._total_latency_ms = 0.0
        self._total_tokens = 0
        self._total_cost = 0.0
        self._errors_by_type: Dict[str, int] = {}

        # Start time
        self._start_time = datetime.now()

        logger.debug(f"Metrics collector initialized for '{name}'")

    def record_request(
        self,
        latency_ms: float,
        success: bool,
        error_type: Optional[str] = None,
        tokens_used: int = 0,
        cost: float = 0.0
    ):
        """
        Record a single request

        Args:
            latency_ms: Request latency in milliseconds
            success: Whether request succeeded
            error_type: Type of error if failed
            tokens_used: Number of tokens consumed
            cost: Cost in USD
        """
        with self._lock:
            # Update counters
            self._total_requests += 1

            if success:
                self._successful_requests += 1
            else:
                self._failed_requests += 1
                if error_type:
                    self._errors_by_type[error_type] = (
                        self._errors_by_type.get(error_type, 0) + 1
                    )

            self._total_latency_ms += latency_ms
            self._total_tokens += tokens_used
            self._total_cost += cost

            # Store detailed data point (if enabled)
            if self.enable_detailed_tracking:
                data_point = MetricDataPoint(
                    timestamp=datetime.now(),
                    latency_ms=latency_ms,
                    success=success,
                    error_type=error_type,
                    tokens_used=tokens_used,
                    cost=cost
                )
                self._data_points.append(data_point)

    def get_metrics(self, window_seconds: Optional[int] = None) -> PerformanceMetrics:
        """
        Get aggregated metrics

        Args:
            window_seconds: Optional time window (None = all time)

        Returns:
            Aggregated performance metrics
        """
        with self._lock:
            # Filter data points by time window
            if window_seconds and self.enable_detailed_tracking:
                cutoff = datetime.now() - timedelta(seconds=window_seconds)
                data_points = [
                    dp for dp in self._data_points
                    if dp.timestamp >= cutoff
                ]
            else:
                data_points = list(self._data_points) if self.enable_detailed_tracking else []

            # Use detailed data if available, otherwise use counters
            if data_points:
                total_requests = len(data_points)
                successful = sum(1 for dp in data_points if dp.success)
                failed = sum(1 for dp in data_points if not dp.success)

                latencies = [dp.latency_ms for dp in data_points]
                latencies_sorted = sorted(latencies)

                avg_latency = sum(latencies) / len(latencies) if latencies else 0
                min_latency = min(latencies) if latencies else 0
                max_latency = max(latencies) if latencies else 0

                p50 = self._percentile(latencies_sorted, 50)
                p95 = self._percentile(latencies_sorted, 95)
                p99 = self._percentile(latencies_sorted, 99)

                total_tokens = sum(dp.tokens_used for dp in data_points)
                total_cost = sum(dp.cost for dp in data_points)

                errors_by_type = {}
                for dp in data_points:
                    if not dp.success and dp.error_type:
                        errors_by_type[dp.error_type] = errors_by_type.get(dp.error_type, 0) + 1

                window_start = data_points[0].timestamp
                window_end = data_points[-1].timestamp

            else:
                # Use running counters
                total_requests = self._total_requests
                successful = self._successful_requests
                failed = self._failed_requests

                avg_latency = (
                    self._total_latency_ms / total_requests
                    if total_requests > 0 else 0
                )
                min_latency = 0
                max_latency = 0
                p50 = p95 = p99 = avg_latency

                total_tokens = self._total_tokens
                total_cost = self._total_cost
                errors_by_type = dict(self._errors_by_type)

                window_start = self._start_time
                window_end = datetime.now()

            # Calculate derived metrics
            error_rate = failed / total_requests if total_requests > 0 else 0

            elapsed_seconds = (window_end - window_start).total_seconds()
            requests_per_second = (
                total_requests / elapsed_seconds
                if elapsed_seconds > 0 else 0
            )

            avg_tokens = total_tokens / total_requests if total_requests > 0 else 0
            avg_cost = total_cost / total_requests if total_requests > 0 else 0

            return PerformanceMetrics(
                total_requests=total_requests,
                successful_requests=successful,
                failed_requests=failed,
                avg_latency_ms=avg_latency,
                min_latency_ms=min_latency,
                max_latency_ms=max_latency,
                p50_latency_ms=p50,
                p95_latency_ms=p95,
                p99_latency_ms=p99,
                requests_per_second=requests_per_second,
                error_rate=error_rate,
                errors_by_type=errors_by_type,
                total_tokens=total_tokens,
                total_cost=total_cost,
                avg_tokens_per_request=avg_tokens,
                avg_cost_per_request=avg_cost,
                window_start=window_start,
                window_end=window_end
            )

    def reset(self):
        """Reset all metrics"""
        with self._lock:
            self._data_points.clear()
            self._total_requests = 0
            self._successful_requests = 0
            self._failed_requests = 0
            self._total_latency_ms = 0.0
            self._total_tokens = 0
            self._total_cost = 0.0
            self._errors_by_type.clear()
            self._start_time = datetime.now()

    def _percentile(self, sorted_values: List[float], percentile: int) -> float:
        """Calculate percentile from sorted values"""
        if not sorted_values:
            return 0.0

        k = (len(sorted_values) - 1) * percentile / 100
        f = int(k)
        c = f + 1

        if c >= len(sorted_values):
            return sorted_values[f]

        # Linear interpolation
        d0 = sorted_values[f] * (c - k)
        d1 = sorted_values[c] * (k - f)
        return d0 + d1


# =============================================================================
# Global Metrics Manager
# =============================================================================

class MetricsManager:
    """Manage metrics collectors for all agents"""

    def __init__(self):
        """Initialize metrics manager"""
        self._collectors: Dict[str, MetricsCollector] = {}
        self._lock = threading.RLock()

    def get_or_create(
        self,
        name: str,
        window_size: int = 10_000,
        enable_detailed_tracking: bool = True
    ) -> MetricsCollector:
        """Get or create metrics collector"""
        with self._lock:
            if name not in self._collectors:
                self._collectors[name] = MetricsCollector(
                    name=name,
                    window_size=window_size,
                    enable_detailed_tracking=enable_detailed_tracking
                )
            return self._collectors[name]

    def get_collector(self, name: str) -> Optional[MetricsCollector]:
        """Get existing collector"""
        return self._collectors.get(name)

    def get_all_metrics(self) -> Dict[str, PerformanceMetrics]:
        """Get metrics from all collectors"""
        with self._lock:
            return {
                name: collector.get_metrics()
                for name, collector in self._collectors.items()
            }

    def get_system_summary(self) -> Dict[str, Any]:
        """Get system-wide metrics summary"""
        with self._lock:
            all_metrics = self.get_all_metrics()

            if not all_metrics:
                return {
                    "total_collectors": 0,
                    "total_requests": 0,
                    "overall_success_rate": 0.0,
                    "overall_error_rate": 0.0
                }

            total_requests = sum(m.total_requests for m in all_metrics.values())
            total_successful = sum(m.successful_requests for m in all_metrics.values())
            total_failed = sum(m.failed_requests for m in all_metrics.values())

            return {
                "total_collectors": len(self._collectors),
                "total_requests": total_requests,
                "total_successful": total_successful,
                "total_failed": total_failed,
                "overall_success_rate": total_successful / total_requests if total_requests > 0 else 0.0,
                "overall_error_rate": total_failed / total_requests if total_requests > 0 else 0.0,
                "agents": list(all_metrics.keys())
            }


# Global metrics manager
_global_metrics_manager = MetricsManager()


def get_metrics_manager() -> MetricsManager:
    """Get global metrics manager"""
    return _global_metrics_manager
