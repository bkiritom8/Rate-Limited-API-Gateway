"""Pydantic models for the API Gateway."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ClientTier(str, Enum):
    """Client tier levels with different rate limits."""
    FREE = "free"
    BASIC = "basic"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"


class RateLimitConfig(BaseModel):
    """Configuration for rate limiting a specific tier."""
    tokens_per_second: float = Field(gt=0, description="Token refill rate")
    max_tokens: int = Field(gt=0, description="Maximum bucket capacity")


class EndpointConfig(BaseModel):
    """Configuration for endpoint-specific token costs."""
    path_pattern: str = Field(description="Regex pattern for matching paths")
    token_cost: int = Field(default=1, ge=1, description="Tokens consumed per request")


class CircuitBreakerConfig(BaseModel):
    """Configuration for circuit breaker."""
    failure_threshold: int = Field(default=5, ge=1, description="Failures before opening")
    recovery_timeout: float = Field(default=30.0, gt=0, description="Seconds before half-open")
    half_open_requests: int = Field(default=3, ge=1, description="Test requests in half-open")


class UpstreamServiceConfig(BaseModel):
    """Configuration for an upstream service."""
    name: str
    base_url: str
    timeout: float = Field(default=30.0, gt=0)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    health_check_path: Optional[str] = "/health"
    health_check_interval: float = Field(default=30.0, gt=0)


class ClientInfo(BaseModel):
    """Information about a client."""
    client_id: str
    tier: ClientTier = ClientTier.FREE
    api_key: Optional[str] = None


class RateLimitResponse(BaseModel):
    """Response when rate limited."""
    error: str = "Rate limit exceeded"
    retry_after: float
    remaining_tokens: float = 0


class MetricsSnapshot(BaseModel):
    """Snapshot of current metrics."""
    total_requests: int
    requests_by_client: dict[str, int]
    rate_limit_hits: dict[str, int]
    average_latency_ms: float
    error_rates: dict[str, float]
    circuit_breaker_states: dict[str, str]


class HealthStatus(BaseModel):
    """Health status of the gateway."""
    status: str
    uptime_seconds: float
    services: dict[str, str]
