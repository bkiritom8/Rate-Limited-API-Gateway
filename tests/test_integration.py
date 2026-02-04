"""Integration tests for the API Gateway."""

import asyncio
import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from api_gateway.main import create_app
from api_gateway.config import GatewayConfig
from api_gateway.models import ClientTier, RateLimitConfig, CircuitBreakerConfig, UpstreamServiceConfig


class TestGatewayIntegration:
    """Integration tests for the full API Gateway."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return GatewayConfig(
            rate_limits={
                ClientTier.FREE: RateLimitConfig(tokens_per_second=10.0, max_tokens=20),
                ClientTier.PREMIUM: RateLimitConfig(tokens_per_second=100.0, max_tokens=200),
            },
            upstream_services={
                "default": UpstreamServiceConfig(
                    name="default",
                    base_url="http://localhost:9999",  # Non-existent for testing
                    timeout=1.0,
                    circuit_breaker=CircuitBreakerConfig(
                        failure_threshold=3,
                        recovery_timeout=1.0,
                    ),
                ),
            },
        )

    @pytest.fixture
    def app(self, config):
        """Create test application."""
        return create_app(config)

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app)

    def test_health_endpoint(self, client):
        """Health endpoint returns healthy status."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_ready_endpoint(self, client):
        """Ready endpoint returns ready status."""
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"

    def test_metrics_endpoint(self, client):
        """Metrics endpoint returns metrics."""
        response = client.get("/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "total_requests" in data
        assert "requests_by_client" in data

    def test_rate_limit_headers(self, client):
        """Responses include rate limit headers."""
        response = client.get("/metrics", headers={"X-API-Key": "test-client"})
        assert response.status_code == 200
        assert "X-RateLimit-Remaining" in response.headers

    def test_rate_limiting(self, client):
        """Rate limiting works correctly."""
        # Make many requests quickly
        responses = []
        for i in range(25):
            response = client.get("/metrics", headers={"X-API-Key": "rate-test-client"})
            responses.append(response)

        # Some should be rate limited (429)
        status_codes = [r.status_code for r in responses]
        assert 429 in status_codes, "Expected some requests to be rate limited"

    def test_rate_limit_retry_after(self, client):
        """Rate limited responses include Retry-After header."""
        # Exhaust rate limit
        for _ in range(25):
            response = client.get("/metrics", headers={"X-API-Key": "retry-test"})

        # Find a 429 response
        response = client.get("/metrics", headers={"X-API-Key": "retry-test"})
        if response.status_code == 429:
            assert "Retry-After" in response.headers

    def test_circuit_breakers_endpoint(self, client):
        """Circuit breakers endpoint returns status."""
        response = client.get("/circuit-breakers")
        assert response.status_code == 200

    def test_latency_metrics_endpoint(self, client):
        """Latency metrics endpoint works."""
        # Generate some traffic first
        for _ in range(5):
            client.get("/metrics")

        response = client.get("/metrics/latency")
        assert response.status_code == 200
        data = response.json()
        assert "p50_ms" in data
        assert "p99_ms" in data

    def test_set_client_tier(self, client):
        """Can set client tier."""
        response = client.post("/clients/new-client/tier?tier=premium")
        assert response.status_code == 200
        data = response.json()
        assert data["tier"] == "premium"

    def test_list_clients(self, client):
        """Can list clients."""
        # Set a client tier first
        client.post("/clients/list-test/tier?tier=basic")

        response = client.get("/clients")
        assert response.status_code == 200


class TestRateLimitMiddleware:
    """Tests specifically for rate limit middleware behavior."""

    @pytest.fixture
    def config(self):
        """Create test configuration with low limits."""
        return GatewayConfig(
            rate_limits={
                ClientTier.FREE: RateLimitConfig(tokens_per_second=1.0, max_tokens=3),
            },
        )

    @pytest.fixture
    def app(self, config):
        """Create test application."""
        return create_app(config)

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app)

    def test_different_clients_independent_limits(self, client):
        """Different clients have independent rate limits."""
        # Exhaust client1's limit
        for _ in range(5):
            client.get("/metrics", headers={"X-API-Key": "client1"})

        # client2 should still have tokens
        response = client.get("/metrics", headers={"X-API-Key": "client2"})
        assert response.status_code == 200

    def test_health_endpoints_not_rate_limited(self, client):
        """Health endpoints bypass rate limiting."""
        # Exhaust limit
        for _ in range(10):
            client.get("/metrics", headers={"X-API-Key": "health-test"})

        # Health should still work
        response = client.get("/health", headers={"X-API-Key": "health-test"})
        assert response.status_code == 200


class TestAsyncConcurrency:
    """Tests for concurrent request handling."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return GatewayConfig(
            rate_limits={
                ClientTier.FREE: RateLimitConfig(tokens_per_second=100.0, max_tokens=50),
            },
        )

    @pytest.fixture
    def app(self, config):
        """Create test application."""
        return create_app(config)

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, app):
        """Handles many concurrent requests."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            # Make 20 concurrent requests
            tasks = [
                client.get("/health")
                for _ in range(20)
            ]

            responses = await asyncio.gather(*tasks)

            # All should succeed
            for response in responses:
                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_concurrent_rate_limiting(self, app):
        """Rate limiting is consistent under concurrent load."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            # Make 100 concurrent requests from same client
            tasks = [
                client.get("/metrics", headers={"X-API-Key": "concurrent-test"})
                for _ in range(100)
            ]

            responses = await asyncio.gather(*tasks)

            # Count successes - should be limited to max_tokens (50)
            successes = sum(1 for r in responses if r.status_code == 200)
            rate_limited = sum(1 for r in responses if r.status_code == 429)

            assert successes <= 50, f"Expected at most 50 successes, got {successes}"
            assert rate_limited >= 50, f"Expected at least 50 rate limited, got {rate_limited}"
