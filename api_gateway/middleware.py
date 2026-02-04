"""Middleware for rate limiting and request processing."""

import time
import re
from typing import Callable, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .rate_limiter import RateLimiter
from .metrics import MetricsCollector, RequestLogger
from .models import ClientTier, RateLimitResponse, EndpointConfig
from .config import GatewayConfig


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces rate limiting on incoming requests.

    Features:
    - Per-client rate limiting
    - Endpoint-specific token costs
    - Retry-After header support
    - Metrics integration
    """

    def __init__(
        self,
        app,
        rate_limiter: RateLimiter,
        config: GatewayConfig,
        metrics: MetricsCollector,
        logger: RequestLogger,
        client_tier_resolver: Optional[Callable[[str], ClientTier]] = None,
    ):
        """
        Initialize middleware.

        Args:
            app: FastAPI application
            rate_limiter: Rate limiter instance
            config: Gateway configuration
            metrics: Metrics collector
            logger: Request logger
            client_tier_resolver: Function to resolve client tier from client_id
        """
        super().__init__(app)
        self._rate_limiter = rate_limiter
        self._config = config
        self._metrics = metrics
        self._logger = logger
        self._tier_resolver = client_tier_resolver or (lambda _: ClientTier.FREE)

    def _get_client_id(self, request: Request) -> str:
        """Extract client ID from request."""
        # Try header first
        client_id = request.headers.get(self._config.client_id_header)

        if not client_id and self._config.fallback_to_ip:
            # Fall back to IP address
            client_id = request.client.host if request.client else "unknown"

        return client_id or "anonymous"

    def _get_token_cost(self, path: str) -> int:
        """Get token cost for a request path."""
        for endpoint in self._config.endpoint_costs:
            if re.match(endpoint.path_pattern, path):
                return endpoint.token_cost
        return 1

    def _is_exempt_path(self, path: str) -> bool:
        """Check if path is exempt from rate limiting."""
        exempt_paths = ["/health", "/metrics", "/ready", "/_internal"]
        return any(path.startswith(p) for p in exempt_paths)

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request with rate limiting."""
        start_time = time.time()
        path = request.url.path
        method = request.method
        client_id = self._get_client_id(request)

        # Skip rate limiting for health/metrics endpoints
        if self._is_exempt_path(path):
            return await call_next(request)

        # Get token cost and client tier
        token_cost = self._get_token_cost(path)
        tier = self._tier_resolver(client_id)

        # Check rate limit
        allowed, retry_after, remaining = await self._rate_limiter.check_rate_limit(
            client_id=client_id,
            tier=tier,
            token_cost=token_cost,
        )

        if not allowed:
            latency_ms = (time.time() - start_time) * 1000

            # Record rate limit hit
            await self._metrics.record_request(
                client_id=client_id,
                path=path,
                method=method,
                status_code=429,
                latency_ms=latency_ms,
                rate_limited=True,
            )

            self._logger.log_request(
                client_id=client_id,
                method=method,
                path=path,
                status_code=429,
                latency_ms=latency_ms,
                rate_limited=True,
            )

            # Return rate limit response
            response_body = RateLimitResponse(
                retry_after=retry_after,
                remaining_tokens=remaining,
            )

            return Response(
                content=response_body.model_dump_json(),
                status_code=429,
                headers={
                    "Content-Type": "application/json",
                    "Retry-After": str(int(retry_after) + 1),
                    "X-RateLimit-Remaining": str(int(remaining)),
                    "X-RateLimit-Reset": str(int(time.time() + retry_after)),
                },
            )

        # Request is allowed, add rate limit headers and proceed
        response = await call_next(request)

        # Add rate limit info headers
        response.headers["X-RateLimit-Remaining"] = str(int(remaining))

        # Record metrics
        latency_ms = (time.time() - start_time) * 1000

        await self._metrics.record_request(
            client_id=client_id,
            path=path,
            method=method,
            status_code=response.status_code,
            latency_ms=latency_ms,
            rate_limited=False,
        )

        self._logger.log_request(
            client_id=client_id,
            method=method,
            path=path,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )

        return response


class ClientTierStore:
    """Simple in-memory store for client tiers."""

    def __init__(self):
        """Initialize store with default tiers."""
        self._tiers: dict[str, ClientTier] = {}

    def get_tier(self, client_id: str) -> ClientTier:
        """Get tier for a client."""
        return self._tiers.get(client_id, ClientTier.FREE)

    def set_tier(self, client_id: str, tier: ClientTier) -> None:
        """Set tier for a client."""
        self._tiers[client_id] = tier

    def remove_client(self, client_id: str) -> None:
        """Remove client from store."""
        self._tiers.pop(client_id, None)

    def list_clients(self) -> dict[str, ClientTier]:
        """List all clients and their tiers."""
        return self._tiers.copy()
