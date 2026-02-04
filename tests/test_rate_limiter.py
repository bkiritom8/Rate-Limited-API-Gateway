"""Tests for the Token Bucket Rate Limiter."""

import asyncio
import pytest
import time

from api_gateway.rate_limiter import RateLimiter, TokenBucket
from api_gateway.models import ClientTier, RateLimitConfig


class TestTokenBucket:
    """Tests for TokenBucket class."""

    def test_initial_tokens(self):
        """Bucket starts with max tokens."""
        bucket = TokenBucket(tokens=10, max_tokens=10, refill_rate=1.0)
        assert bucket.available_tokens == 10

    def test_consume_success(self):
        """Consuming available tokens succeeds."""
        bucket = TokenBucket(tokens=10, max_tokens=10, refill_rate=1.0)
        success, retry_after = bucket.consume(5)
        assert success is True
        assert retry_after == 0.0
        assert bucket.available_tokens == 5

    def test_consume_insufficient_tokens(self):
        """Consuming more tokens than available fails."""
        bucket = TokenBucket(tokens=5, max_tokens=10, refill_rate=1.0)
        success, retry_after = bucket.consume(10)
        assert success is False
        assert retry_after > 0

    def test_refill_over_time(self):
        """Tokens refill over time."""
        bucket = TokenBucket(tokens=0, max_tokens=10, refill_rate=10.0)
        time.sleep(0.1)  # Wait for refill
        assert bucket.available_tokens >= 0.5  # At least 0.5 tokens refilled

    def test_refill_capped_at_max(self):
        """Refill doesn't exceed max tokens."""
        bucket = TokenBucket(tokens=10, max_tokens=10, refill_rate=100.0)
        time.sleep(0.1)
        assert bucket.available_tokens == 10


class TestRateLimiter:
    """Tests for RateLimiter class."""

    @pytest.fixture
    def rate_configs(self):
        """Create test rate configurations."""
        return {
            ClientTier.FREE: RateLimitConfig(tokens_per_second=1.0, max_tokens=5),
            ClientTier.PREMIUM: RateLimitConfig(tokens_per_second=10.0, max_tokens=50),
        }

    @pytest.fixture
    def rate_limiter(self, rate_configs):
        """Create rate limiter instance."""
        return RateLimiter(rate_configs)

    @pytest.mark.asyncio
    async def test_first_request_allowed(self, rate_limiter):
        """First request from new client is allowed."""
        allowed, retry_after, remaining = await rate_limiter.check_rate_limit(
            "client1", ClientTier.FREE, 1
        )
        assert allowed is True
        assert retry_after == 0
        assert remaining == 4  # 5 - 1

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self, rate_limiter):
        """Requests are denied when rate limit exceeded."""
        client_id = "client2"

        # Consume all tokens
        for _ in range(5):
            await rate_limiter.check_rate_limit(client_id, ClientTier.FREE, 1)

        # Next request should be denied
        allowed, retry_after, remaining = await rate_limiter.check_rate_limit(
            client_id, ClientTier.FREE, 1
        )
        assert allowed is False
        assert retry_after > 0
        assert remaining == 0

    @pytest.mark.asyncio
    async def test_premium_tier_higher_limits(self, rate_limiter):
        """Premium tier has higher rate limits."""
        client_id = "premium_client"

        # Should be able to make many requests
        for i in range(30):
            allowed, _, _ = await rate_limiter.check_rate_limit(
                client_id, ClientTier.PREMIUM, 1
            )
            assert allowed is True, f"Request {i+1} should be allowed"

    @pytest.mark.asyncio
    async def test_token_cost(self, rate_limiter):
        """Higher token cost consumes more tokens."""
        client_id = "cost_client"

        # First request costs 3 tokens
        allowed, _, remaining = await rate_limiter.check_rate_limit(
            client_id, ClientTier.FREE, 3
        )
        assert allowed is True
        assert remaining == 2  # 5 - 3

    @pytest.mark.asyncio
    async def test_get_client_status(self, rate_limiter):
        """Can retrieve client rate limit status."""
        client_id = "status_client"

        await rate_limiter.check_rate_limit(client_id, ClientTier.FREE, 2)

        status = await rate_limiter.get_client_status(client_id)
        assert status is not None
        assert status["client_id"] == client_id
        assert status["tier"] == "free"
        assert status["available_tokens"] == 3

    @pytest.mark.asyncio
    async def test_reset_client(self, rate_limiter):
        """Can reset a client's rate limit."""
        client_id = "reset_client"

        # Consume some tokens
        await rate_limiter.check_rate_limit(client_id, ClientTier.FREE, 4)

        # Reset
        success = await rate_limiter.reset_client(client_id)
        assert success is True

        # Should have full tokens again
        status = await rate_limiter.get_client_status(client_id)
        assert status["available_tokens"] == 5

    @pytest.mark.asyncio
    async def test_remove_client(self, rate_limiter):
        """Can remove a client from rate limiter."""
        client_id = "remove_client"

        await rate_limiter.check_rate_limit(client_id, ClientTier.FREE, 1)
        assert await rate_limiter.get_client_status(client_id) is not None

        success = await rate_limiter.remove_client(client_id)
        assert success is True
        assert await rate_limiter.get_client_status(client_id) is None

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, rate_limiter):
        """Handles concurrent requests correctly."""
        client_id = "concurrent_client"

        async def make_request():
            return await rate_limiter.check_rate_limit(client_id, ClientTier.FREE, 1)

        # Make 10 concurrent requests
        results = await asyncio.gather(*[make_request() for _ in range(10)])

        # Only 5 should be allowed (max tokens)
        allowed_count = sum(1 for allowed, _, _ in results if allowed)
        assert allowed_count == 5
