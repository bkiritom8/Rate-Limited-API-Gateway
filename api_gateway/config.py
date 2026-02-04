"""Configuration management for the API Gateway."""

import os
from typing import Optional
from pydantic import BaseModel, Field

from .models import (
    ClientTier,
    RateLimitConfig,
    EndpointConfig,
    UpstreamServiceConfig,
    CircuitBreakerConfig,
)


class GatewayConfig(BaseModel):
    """Main configuration for the API Gateway."""

    # Server settings
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080)

    # Rate limit configs per tier
    rate_limits: dict[ClientTier, RateLimitConfig] = Field(
        default_factory=lambda: {
            ClientTier.FREE: RateLimitConfig(tokens_per_second=1.0, max_tokens=10),
            ClientTier.BASIC: RateLimitConfig(tokens_per_second=5.0, max_tokens=50),
            ClientTier.PREMIUM: RateLimitConfig(tokens_per_second=20.0, max_tokens=200),
            ClientTier.ENTERPRISE: RateLimitConfig(tokens_per_second=100.0, max_tokens=1000),
        }
    )

    # Endpoint-specific token costs
    endpoint_costs: list[EndpointConfig] = Field(
        default_factory=lambda: [
            EndpointConfig(path_pattern=r"^/api/v1/search.*", token_cost=5),
            EndpointConfig(path_pattern=r"^/api/v1/export.*", token_cost=10),
            EndpointConfig(path_pattern=r"^/api/v1/bulk.*", token_cost=20),
            EndpointConfig(path_pattern=r"^/api/v1/.*", token_cost=1),
        ]
    )

    # Upstream services
    upstream_services: dict[str, UpstreamServiceConfig] = Field(
        default_factory=lambda: {
            "default": UpstreamServiceConfig(
                name="default",
                base_url="http://localhost:9000",
                timeout=30.0,
                circuit_breaker=CircuitBreakerConfig(
                    failure_threshold=5,
                    recovery_timeout=30.0,
                    half_open_requests=3,
                ),
            )
        }
    )

    # Default client identification method
    client_id_header: str = "X-API-Key"
    fallback_to_ip: bool = True

    # Metrics settings
    metrics_enabled: bool = True
    metrics_retention_seconds: int = 3600

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        """Create configuration from environment variables."""
        config = cls()

        if host := os.getenv("GATEWAY_HOST"):
            config.host = host
        if port := os.getenv("GATEWAY_PORT"):
            config.port = int(port)
        if header := os.getenv("GATEWAY_CLIENT_ID_HEADER"):
            config.client_id_header = header

        return config


# Global configuration instance
_config: Optional[GatewayConfig] = None


def get_config() -> GatewayConfig:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = GatewayConfig.from_env()
    return _config


def set_config(config: GatewayConfig) -> None:
    """Set the global configuration instance."""
    global _config
    _config = config
