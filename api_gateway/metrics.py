"""Observability and Metrics for the API Gateway."""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional
import logging

from .models import MetricsSnapshot

logger = logging.getLogger(__name__)


@dataclass
class RequestMetric:
    """Single request metric record."""
    timestamp: float
    client_id: str
    path: str
    method: str
    status_code: int
    latency_ms: float
    rate_limited: bool = False
    service: Optional[str] = None
    error: Optional[str] = None


@dataclass
class AggregatedMetrics:
    """Aggregated metrics over a time window."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rate_limited_requests: int = 0
    total_latency_ms: float = 0.0
    requests_by_client: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    requests_by_path: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    requests_by_service: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    errors_by_service: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    rate_limit_hits_by_client: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    latencies: list[float] = field(default_factory=list)


class MetricsCollector:
    """
    Collects and aggregates metrics for the API Gateway.

    Features:
    - Request counting per client
    - Rate limit hit tracking
    - Latency tracking with percentiles
    - Error rate by service
    - Time-windowed metrics retention
    """

    def __init__(self, retention_seconds: int = 3600):
        """
        Initialize metrics collector.

        Args:
            retention_seconds: How long to retain metrics
        """
        self._retention_seconds = retention_seconds
        self._metrics: list[RequestMetric] = []
        self._lock = asyncio.Lock()
        self._start_time = time.time()

    async def record_request(
        self,
        client_id: str,
        path: str,
        method: str,
        status_code: int,
        latency_ms: float,
        rate_limited: bool = False,
        service: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Record a request metric.

        Args:
            client_id: Client identifier
            path: Request path
            method: HTTP method
            status_code: Response status code
            latency_ms: Request latency in milliseconds
            rate_limited: Whether request was rate limited
            service: Upstream service name
            error: Error message if any
        """
        metric = RequestMetric(
            timestamp=time.time(),
            client_id=client_id,
            path=path,
            method=method,
            status_code=status_code,
            latency_ms=latency_ms,
            rate_limited=rate_limited,
            service=service,
            error=error,
        )

        async with self._lock:
            self._metrics.append(metric)
            # Cleanup old metrics periodically
            if len(self._metrics) % 1000 == 0:
                await self._cleanup_old_metrics()

    async def _cleanup_old_metrics(self) -> None:
        """Remove metrics older than retention period."""
        cutoff = time.time() - self._retention_seconds
        self._metrics = [m for m in self._metrics if m.timestamp > cutoff]

    async def get_aggregated_metrics(
        self, window_seconds: Optional[int] = None
    ) -> AggregatedMetrics:
        """
        Get aggregated metrics for a time window.

        Args:
            window_seconds: Time window (default: all retained metrics)

        Returns:
            Aggregated metrics
        """
        async with self._lock:
            cutoff = time.time() - (window_seconds or self._retention_seconds)
            recent = [m for m in self._metrics if m.timestamp > cutoff]

            agg = AggregatedMetrics()
            agg.total_requests = len(recent)

            for m in recent:
                # Count by status
                if 200 <= m.status_code < 400:
                    agg.successful_requests += 1
                else:
                    agg.failed_requests += 1

                if m.rate_limited:
                    agg.rate_limited_requests += 1
                    agg.rate_limit_hits_by_client[m.client_id] += 1

                # Aggregate by dimensions
                agg.requests_by_client[m.client_id] += 1
                agg.requests_by_path[m.path] += 1

                if m.service:
                    agg.requests_by_service[m.service] += 1
                    if m.status_code >= 500 or m.error:
                        agg.errors_by_service[m.service] += 1

                # Track latency
                agg.total_latency_ms += m.latency_ms
                agg.latencies.append(m.latency_ms)

            return agg

    async def get_snapshot(self, window_seconds: int = 300) -> MetricsSnapshot:
        """
        Get a metrics snapshot for external consumption.

        Args:
            window_seconds: Time window for metrics

        Returns:
            MetricsSnapshot model
        """
        agg = await self.get_aggregated_metrics(window_seconds)

        # Calculate average latency
        avg_latency = (
            agg.total_latency_ms / len(agg.latencies) if agg.latencies else 0.0
        )

        # Calculate error rates by service
        error_rates = {}
        for service, count in agg.requests_by_service.items():
            errors = agg.errors_by_service.get(service, 0)
            error_rates[service] = errors / count if count > 0 else 0.0

        return MetricsSnapshot(
            total_requests=agg.total_requests,
            requests_by_client=dict(agg.requests_by_client),
            rate_limit_hits=dict(agg.rate_limit_hits_by_client),
            average_latency_ms=avg_latency,
            error_rates=error_rates,
            circuit_breaker_states={},  # Filled by main app
        )

    async def get_percentile_latency(
        self, percentile: float, window_seconds: int = 300
    ) -> float:
        """
        Get latency at a specific percentile.

        Args:
            percentile: Percentile (0-100)
            window_seconds: Time window

        Returns:
            Latency in milliseconds
        """
        agg = await self.get_aggregated_metrics(window_seconds)

        if not agg.latencies:
            return 0.0

        sorted_latencies = sorted(agg.latencies)
        index = int(len(sorted_latencies) * percentile / 100)
        index = min(index, len(sorted_latencies) - 1)
        return sorted_latencies[index]

    def get_uptime_seconds(self) -> float:
        """Get gateway uptime in seconds."""
        return time.time() - self._start_time

    async def get_client_metrics(
        self, client_id: str, window_seconds: int = 300
    ) -> dict:
        """
        Get metrics for a specific client.

        Args:
            client_id: Client identifier
            window_seconds: Time window

        Returns:
            Client-specific metrics
        """
        async with self._lock:
            cutoff = time.time() - window_seconds
            client_metrics = [
                m for m in self._metrics
                if m.timestamp > cutoff and m.client_id == client_id
            ]

            total = len(client_metrics)
            rate_limited = sum(1 for m in client_metrics if m.rate_limited)
            errors = sum(1 for m in client_metrics if m.status_code >= 400)
            latencies = [m.latency_ms for m in client_metrics]

            return {
                "client_id": client_id,
                "total_requests": total,
                "rate_limited_requests": rate_limited,
                "error_requests": errors,
                "average_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
                "p50_latency_ms": sorted(latencies)[len(latencies) // 2] if latencies else 0,
                "p99_latency_ms": sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0,
            }


class RequestLogger:
    """Structured logging for requests."""

    def __init__(self, log_level: int = logging.INFO):
        """Initialize request logger."""
        self._logger = logging.getLogger("api_gateway.requests")
        self._logger.setLevel(log_level)

    def log_request(
        self,
        client_id: str,
        method: str,
        path: str,
        status_code: int,
        latency_ms: float,
        rate_limited: bool = False,
        error: Optional[str] = None,
    ) -> None:
        """Log a request with structured fields."""
        log_data = {
            "client_id": client_id,
            "method": method,
            "path": path,
            "status_code": status_code,
            "latency_ms": round(latency_ms, 2),
            "rate_limited": rate_limited,
        }

        if error:
            log_data["error"] = error
            self._logger.error("Request failed", extra=log_data)
        elif rate_limited:
            self._logger.warning("Request rate limited", extra=log_data)
        else:
            self._logger.info("Request completed", extra=log_data)
