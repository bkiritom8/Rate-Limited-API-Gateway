"""Token Bucket Rate Limiter implementation."""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from .models import ClientTier, RateLimitConfig


@dataclass
class TokenBucket:
    """Token bucket for a single client."""

    tokens: float
    max_tokens: int
    refill_rate: float  # tokens per second
    last_refill: float = field(default_factory=time.monotonic)

    def refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def consume(self, tokens: int = 1) -> tuple[bool, float]:
        """
        Try to consume tokens from the bucket.

        Returns:
            tuple of (success, retry_after_seconds)
            If success is True, retry_after is 0
            If success is False, retry_after indicates when tokens will be available
        """
        self.refill()

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True, 0.0

        # Calculate time until enough tokens are available
        tokens_needed = tokens - self.tokens
        retry_after = tokens_needed / self.refill_rate
        return False, retry_after

    @property
    def available_tokens(self) -> float:
        """Get current available tokens (with refill)."""
        self.refill()
        return self.tokens


class RateLimiter:
    """
    Rate limiter using token bucket algorithm.

    Manages per-client rate limiting with configurable tiers.
    Thread-safe through asyncio locks.
    """

    def __init__(self, rate_configs: dict[ClientTier, RateLimitConfig]):
        """
        Initialize the rate limiter.

        Args:
            rate_configs: Rate limit configuration per tier
        """
        self._rate_configs = rate_configs
        self._buckets: dict[str, TokenBucket] = {}
        self._client_tiers: dict[str, ClientTier] = {}
        self._lock = asyncio.Lock()

    def _get_or_create_bucket(self, client_id: str, tier: ClientTier) -> TokenBucket:
        """Get existing bucket or create new one for client."""
        if client_id not in self._buckets:
            config = self._rate_configs.get(tier, self._rate_configs[ClientTier.FREE])
            self._buckets[client_id] = TokenBucket(
                tokens=config.max_tokens,
                max_tokens=config.max_tokens,
                refill_rate=config.tokens_per_second,
            )
            self._client_tiers[client_id] = tier
        return self._buckets[client_id]

    async def check_rate_limit(
        self,
        client_id: str,
        tier: ClientTier = ClientTier.FREE,
        token_cost: int = 1,
    ) -> tuple[bool, float, float]:
        """
        Check if a request is allowed under the rate limit.

        Args:
            client_id: Unique identifier for the client
            tier: Client's tier level
            token_cost: Number of tokens this request costs

        Returns:
            tuple of (allowed, retry_after_seconds, remaining_tokens)
        """
        async with self._lock:
            bucket = self._get_or_create_bucket(client_id, tier)

            # Update tier if changed
            if self._client_tiers.get(client_id) != tier:
                config = self._rate_configs.get(tier, self._rate_configs[ClientTier.FREE])
                bucket.max_tokens = config.max_tokens
                bucket.refill_rate = config.tokens_per_second
                self._client_tiers[client_id] = tier

            allowed, retry_after = bucket.consume(token_cost)
            return allowed, retry_after, bucket.available_tokens

    async def get_client_status(self, client_id: str) -> Optional[dict]:
        """Get current rate limit status for a client."""
        async with self._lock:
            if client_id not in self._buckets:
                return None

            bucket = self._buckets[client_id]
            tier = self._client_tiers.get(client_id, ClientTier.FREE)
            config = self._rate_configs.get(tier)

            return {
                "client_id": client_id,
                "tier": tier.value,
                "available_tokens": bucket.available_tokens,
                "max_tokens": bucket.max_tokens,
                "refill_rate": bucket.refill_rate,
                "tokens_per_second": config.tokens_per_second if config else 0,
            }

    async def reset_client(self, client_id: str) -> bool:
        """Reset a client's bucket to full capacity."""
        async with self._lock:
            if client_id in self._buckets:
                bucket = self._buckets[client_id]
                bucket.tokens = bucket.max_tokens
                bucket.last_refill = time.monotonic()
                return True
            return False

    async def remove_client(self, client_id: str) -> bool:
        """Remove a client from the rate limiter."""
        async with self._lock:
            if client_id in self._buckets:
                del self._buckets[client_id]
                self._client_tiers.pop(client_id, None)
                return True
            return False

    async def get_all_clients(self) -> list[str]:
        """Get list of all tracked client IDs."""
        async with self._lock:
            return list(self._buckets.keys())

    async def cleanup_inactive(self, max_idle_seconds: float = 3600) -> int:
        """
        Remove clients that haven't made requests recently.

        Args:
            max_idle_seconds: Remove clients idle for longer than this

        Returns:
            Number of clients removed
        """
        async with self._lock:
            now = time.monotonic()
            to_remove = []

            for client_id, bucket in self._buckets.items():
                if now - bucket.last_refill > max_idle_seconds:
                    to_remove.append(client_id)

            for client_id in to_remove:
                del self._buckets[client_id]
                self._client_tiers.pop(client_id, None)

            return len(to_remove)
