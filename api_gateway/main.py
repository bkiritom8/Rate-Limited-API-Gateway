"""Main FastAPI application for the Rate-Limited API Gateway."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse

from .config import GatewayConfig, get_config, set_config
from .models import (
    ClientTier,
    ClientInfo,
    MetricsSnapshot,
    HealthStatus,
)
from .rate_limiter import RateLimiter
from .circuit_breaker import CircuitBreakerRegistry, CircuitOpenError
from .router import RequestRouter, HealthChecker, UpstreamTimeoutError, UpstreamConnectionError
from .metrics import MetricsCollector, RequestLogger
from .middleware import RateLimitMiddleware, ClientTierStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global instances
rate_limiter: Optional[RateLimiter] = None
circuit_registry: Optional[CircuitBreakerRegistry] = None
request_router: Optional[RequestRouter] = None
health_checker: Optional[HealthChecker] = None
metrics_collector: Optional[MetricsCollector] = None
request_logger: Optional[RequestLogger] = None
client_tier_store: Optional[ClientTierStore] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global rate_limiter, circuit_registry, request_router
    global health_checker, metrics_collector, request_logger, client_tier_store

    config = get_config()

    # Initialize components
    logger.info("Initializing API Gateway components...")

    rate_limiter = RateLimiter(config.rate_limits)
    circuit_registry = CircuitBreakerRegistry()
    metrics_collector = MetricsCollector(config.metrics_retention_seconds)
    request_logger = RequestLogger()
    client_tier_store = ClientTierStore()

    request_router = RequestRouter(
        upstream_services=config.upstream_services,
        endpoint_costs=config.endpoint_costs,
        circuit_registry=circuit_registry,
    )

    health_checker = HealthChecker(
        services=config.upstream_services,
        circuit_registry=circuit_registry,
    )

    # Start components
    await request_router.start()
    await health_checker.start()

    logger.info("API Gateway started successfully")

    yield

    # Shutdown
    logger.info("Shutting down API Gateway...")
    await request_router.stop()
    await health_checker.stop()
    logger.info("API Gateway shutdown complete")


def create_app(config: Optional[GatewayConfig] = None) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        config: Optional configuration (uses default if not provided)

    Returns:
        Configured FastAPI application
    """
    if config:
        set_config(config)

    app = FastAPI(
        title="Rate-Limited API Gateway",
        description="API Gateway with rate limiting, circuit breaker, and observability",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Add middleware after lifespan sets up components
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        """Apply rate limiting to requests."""
        if rate_limiter is None or metrics_collector is None or request_logger is None:
            return await call_next(request)

        middleware = RateLimitMiddleware(
            app=app,
            rate_limiter=rate_limiter,
            config=get_config(),
            metrics=metrics_collector,
            logger=request_logger,
            client_tier_resolver=lambda cid: client_tier_store.get_tier(cid) if client_tier_store else ClientTier.FREE,
        )
        return await middleware.dispatch(request, call_next)

    # Health and readiness endpoints
    @app.get("/health", tags=["Health"])
    async def health_check() -> HealthStatus:
        """Check gateway health."""
        service_health = health_checker.get_health_status() if health_checker else {}
        service_status = {
            name: "healthy" if healthy else "unhealthy"
            for name, healthy in service_health.items()
        }

        return HealthStatus(
            status="healthy",
            uptime_seconds=metrics_collector.get_uptime_seconds() if metrics_collector else 0,
            services=service_status,
        )

    @app.get("/ready", tags=["Health"])
    async def readiness_check():
        """Check if gateway is ready to accept traffic."""
        return {"status": "ready"}

    # Metrics endpoints
    @app.get("/metrics", tags=["Metrics"])
    async def get_metrics(window_seconds: int = 300) -> MetricsSnapshot:
        """Get current metrics snapshot."""
        if not metrics_collector:
            raise HTTPException(status_code=503, detail="Metrics not available")

        snapshot = await metrics_collector.get_snapshot(window_seconds)

        # Add circuit breaker states
        if circuit_registry:
            cb_status = await circuit_registry.get_all_status()
            snapshot.circuit_breaker_states = {
                name: status["state"] for name, status in cb_status.items()
            }

        return snapshot

    @app.get("/metrics/latency", tags=["Metrics"])
    async def get_latency_percentiles(window_seconds: int = 300):
        """Get latency percentiles."""
        if not metrics_collector:
            raise HTTPException(status_code=503, detail="Metrics not available")

        p50 = await metrics_collector.get_percentile_latency(50, window_seconds)
        p90 = await metrics_collector.get_percentile_latency(90, window_seconds)
        p95 = await metrics_collector.get_percentile_latency(95, window_seconds)
        p99 = await metrics_collector.get_percentile_latency(99, window_seconds)

        return {
            "p50_ms": round(p50, 2),
            "p90_ms": round(p90, 2),
            "p95_ms": round(p95, 2),
            "p99_ms": round(p99, 2),
            "window_seconds": window_seconds,
        }

    @app.get("/metrics/client/{client_id}", tags=["Metrics"])
    async def get_client_metrics(client_id: str, window_seconds: int = 300):
        """Get metrics for a specific client."""
        if not metrics_collector:
            raise HTTPException(status_code=503, detail="Metrics not available")

        return await metrics_collector.get_client_metrics(client_id, window_seconds)

    # Circuit breaker endpoints
    @app.get("/circuit-breakers", tags=["Circuit Breaker"])
    async def get_circuit_breakers():
        """Get status of all circuit breakers."""
        if not circuit_registry:
            raise HTTPException(status_code=503, detail="Circuit breakers not available")

        return await circuit_registry.get_all_status()

    @app.post("/circuit-breakers/reset", tags=["Circuit Breaker"])
    async def reset_circuit_breakers():
        """Reset all circuit breakers to closed state."""
        if not circuit_registry:
            raise HTTPException(status_code=503, detail="Circuit breakers not available")

        await circuit_registry.reset_all()
        return {"status": "reset", "message": "All circuit breakers reset to closed state"}

    # Rate limit management endpoints
    @app.get("/rate-limits/status/{client_id}", tags=["Rate Limits"])
    async def get_rate_limit_status(client_id: str):
        """Get rate limit status for a client."""
        if not rate_limiter:
            raise HTTPException(status_code=503, detail="Rate limiter not available")

        status = await rate_limiter.get_client_status(client_id)
        if not status:
            raise HTTPException(status_code=404, detail="Client not found")

        return status

    @app.post("/rate-limits/reset/{client_id}", tags=["Rate Limits"])
    async def reset_client_rate_limit(client_id: str):
        """Reset rate limit for a specific client."""
        if not rate_limiter:
            raise HTTPException(status_code=503, detail="Rate limiter not available")

        success = await rate_limiter.reset_client(client_id)
        if not success:
            raise HTTPException(status_code=404, detail="Client not found")

        return {"status": "reset", "client_id": client_id}

    # Client tier management
    @app.get("/clients", tags=["Clients"])
    async def list_clients():
        """List all known clients and their tiers."""
        if not client_tier_store:
            raise HTTPException(status_code=503, detail="Client store not available")

        return client_tier_store.list_clients()

    @app.post("/clients/{client_id}/tier", tags=["Clients"])
    async def set_client_tier(client_id: str, tier: ClientTier):
        """Set the tier for a client."""
        if not client_tier_store:
            raise HTTPException(status_code=503, detail="Client store not available")

        client_tier_store.set_tier(client_id, tier)
        return {"client_id": client_id, "tier": tier.value}

    # Proxy endpoint - catch-all for routing to upstream services
    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
        tags=["Proxy"],
    )
    async def proxy_request(request: Request, path: str):
        """Proxy requests to upstream services."""
        if not request_router:
            raise HTTPException(status_code=503, detail="Router not available")

        try:
            return await request_router.proxy_request(request)
        except CircuitOpenError as e:
            return JSONResponse(
                status_code=503,
                content={"error": "Service unavailable", "detail": str(e)},
                headers={"Retry-After": "30"},
            )
        except UpstreamTimeoutError as e:
            return JSONResponse(
                status_code=504,
                content={"error": "Gateway timeout", "detail": str(e)},
            )
        except UpstreamConnectionError as e:
            return JSONResponse(
                status_code=502,
                content={"error": "Bad gateway", "detail": str(e)},
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    return app


# Create default app instance
app = create_app()


def run_server(host: str = "0.0.0.0", port: int = 8080):
    """Run the server with uvicorn."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
