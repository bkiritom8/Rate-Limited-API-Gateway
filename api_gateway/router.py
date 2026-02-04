"""Request Router and Proxy for upstream services."""

import asyncio
import re
from typing import Optional
from urllib.parse import urljoin

import httpx
from fastapi import Request, Response

from .models import UpstreamServiceConfig, EndpointConfig
from .circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitOpenError


class RequestRouter:
    """
    Routes and proxies requests to upstream services.

    Features:
    - Path-based routing to different upstream services
    - Circuit breaker integration
    - Configurable timeouts
    - Request/response forwarding
    """

    def __init__(
        self,
        upstream_services: dict[str, UpstreamServiceConfig],
        endpoint_costs: list[EndpointConfig],
        circuit_registry: CircuitBreakerRegistry,
    ):
        """
        Initialize the router.

        Args:
            upstream_services: Configuration for upstream services
            endpoint_costs: Token cost configuration per endpoint
            circuit_registry: Registry of circuit breakers
        """
        self._services = upstream_services
        self._endpoint_costs = endpoint_costs
        self._circuit_registry = circuit_registry
        self._route_patterns: list[tuple[re.Pattern, str]] = []
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        """Start the router and initialize HTTP client."""
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    async def stop(self) -> None:
        """Stop the router and close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def add_route(self, pattern: str, service_name: str) -> None:
        """
        Add a routing rule.

        Args:
            pattern: Regex pattern to match paths
            service_name: Name of upstream service to route to
        """
        self._route_patterns.append((re.compile(pattern), service_name))

    def get_token_cost(self, path: str) -> int:
        """
        Get the token cost for a request path.

        Args:
            path: Request path

        Returns:
            Token cost (default 1)
        """
        for endpoint in self._endpoint_costs:
            if re.match(endpoint.path_pattern, path):
                return endpoint.token_cost
        return 1

    def resolve_service(self, path: str) -> Optional[str]:
        """
        Resolve which service should handle a path.

        Args:
            path: Request path

        Returns:
            Service name or None if no match
        """
        for pattern, service_name in self._route_patterns:
            if pattern.match(path):
                return service_name

        # Default to 'default' service if configured
        if "default" in self._services:
            return "default"

        return None

    async def proxy_request(
        self,
        request: Request,
        service_name: Optional[str] = None,
    ) -> Response:
        """
        Proxy a request to an upstream service.

        Args:
            request: Incoming FastAPI request
            service_name: Target service (resolved from path if not provided)

        Returns:
            Response from upstream service

        Raises:
            ValueError: If service not found
            CircuitOpenError: If circuit breaker is open
        """
        if not self._client:
            raise RuntimeError("Router not started")

        # Resolve service
        target_service = service_name or self.resolve_service(request.url.path)
        if not target_service or target_service not in self._services:
            raise ValueError(f"Unknown service: {target_service}")

        service_config = self._services[target_service]

        # Get circuit breaker
        circuit = await self._circuit_registry.get_or_create(
            target_service, service_config.circuit_breaker
        )

        # Check circuit breaker
        can_execute, reason = await circuit.can_execute()
        if not can_execute:
            raise CircuitOpenError(reason)

        # Build upstream URL
        upstream_url = urljoin(
            service_config.base_url,
            request.url.path + ("?" + request.url.query if request.url.query else ""),
        )

        # Forward headers (excluding hop-by-hop headers)
        hop_by_hop = {
            "connection", "keep-alive", "proxy-authenticate",
            "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade"
        }
        headers = {
            k: v for k, v in request.headers.items()
            if k.lower() not in hop_by_hop and k.lower() != "host"
        }

        # Get request body
        body = await request.body()

        try:
            # Make upstream request
            upstream_response = await self._client.request(
                method=request.method,
                url=upstream_url,
                headers=headers,
                content=body,
                timeout=service_config.timeout,
            )

            await circuit.record_success()

            # Build response
            response_headers = {
                k: v for k, v in upstream_response.headers.items()
                if k.lower() not in hop_by_hop
            }

            return Response(
                content=upstream_response.content,
                status_code=upstream_response.status_code,
                headers=response_headers,
            )

        except httpx.TimeoutException as e:
            await circuit.record_failure()
            raise UpstreamTimeoutError(f"Timeout connecting to {target_service}") from e
        except httpx.ConnectError as e:
            await circuit.record_failure()
            raise UpstreamConnectionError(f"Cannot connect to {target_service}") from e
        except Exception as e:
            await circuit.record_failure()
            raise


class HealthChecker:
    """Periodically checks health of upstream services."""

    def __init__(
        self,
        services: dict[str, UpstreamServiceConfig],
        circuit_registry: CircuitBreakerRegistry,
    ):
        """
        Initialize health checker.

        Args:
            services: Upstream service configurations
            circuit_registry: Circuit breaker registry
        """
        self._services = services
        self._circuit_registry = circuit_registry
        self._health_status: dict[str, bool] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        """Start periodic health checking."""
        self._running = True
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
        self._task = asyncio.create_task(self._check_loop())

    async def stop(self) -> None:
        """Stop health checking."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()

    async def _check_loop(self) -> None:
        """Main health check loop."""
        while self._running:
            await self._check_all_services()
            # Wait for minimum interval
            min_interval = min(
                (s.health_check_interval for s in self._services.values()),
                default=30.0
            )
            await asyncio.sleep(min_interval)

    async def _check_all_services(self) -> None:
        """Check health of all services."""
        tasks = [
            self._check_service(name, config)
            for name, config in self._services.items()
            if config.health_check_path
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_service(self, name: str, config: UpstreamServiceConfig) -> None:
        """Check health of a single service."""
        if not config.health_check_path:
            return

        url = urljoin(config.base_url, config.health_check_path)

        try:
            response = await self._client.get(url)
            healthy = 200 <= response.status_code < 300
            self._health_status[name] = healthy
        except Exception:
            self._health_status[name] = False

    def get_health_status(self) -> dict[str, bool]:
        """Get current health status of all services."""
        return self._health_status.copy()


class UpstreamTimeoutError(Exception):
    """Raised when upstream request times out."""
    pass


class UpstreamConnectionError(Exception):
    """Raised when cannot connect to upstream."""
    pass
