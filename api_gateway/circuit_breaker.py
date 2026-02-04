"""Circuit Breaker implementation for downstream service protection."""

import asyncio
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Callable, Any

from .models import CircuitBreakerConfig


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation, requests pass through
    OPEN = "open"          # Failing, requests are rejected
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitStats:
    """Statistics for a circuit breaker."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    state_changed_at: float = field(default_factory=time.monotonic)


class CircuitBreaker:
    """
    Circuit breaker for a single downstream service.

    States:
    - CLOSED: Normal operation, all requests pass through
    - OPEN: Service is failing, requests are rejected immediately
    - HALF_OPEN: Testing recovery, limited requests allowed

    Transitions:
    - CLOSED -> OPEN: After N consecutive failures
    - OPEN -> HALF_OPEN: After recovery timeout
    - HALF_OPEN -> CLOSED: After N successful test requests
    - HALF_OPEN -> OPEN: On any failure
    """

    def __init__(self, service_name: str, config: CircuitBreakerConfig):
        """
        Initialize circuit breaker.

        Args:
            service_name: Name of the downstream service
            config: Circuit breaker configuration
        """
        self.service_name = service_name
        self.config = config
        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._half_open_count = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    @property
    def stats(self) -> CircuitStats:
        """Get current statistics."""
        return self._stats

    def _should_transition_to_half_open(self) -> bool:
        """Check if enough time passed to try half-open."""
        if self._state != CircuitState.OPEN:
            return False

        if self._stats.last_failure_time is None:
            return True

        elapsed = time.monotonic() - self._stats.last_failure_time
        return elapsed >= self.config.recovery_timeout

    async def can_execute(self) -> tuple[bool, Optional[str]]:
        """
        Check if a request can be executed.

        Returns:
            tuple of (can_execute, rejection_reason)
        """
        async with self._lock:
            # Check for state transition from OPEN to HALF_OPEN
            if self._should_transition_to_half_open():
                self._transition_to(CircuitState.HALF_OPEN)
                self._half_open_count = 0

            if self._state == CircuitState.CLOSED:
                return True, None

            if self._state == CircuitState.OPEN:
                time_until_retry = self.config.recovery_timeout
                if self._stats.last_failure_time:
                    elapsed = time.monotonic() - self._stats.last_failure_time
                    time_until_retry = max(0, self.config.recovery_timeout - elapsed)
                return False, f"Circuit open for {self.service_name}, retry in {time_until_retry:.1f}s"

            # HALF_OPEN state - allow limited requests
            if self._half_open_count < self.config.half_open_requests:
                self._half_open_count += 1
                return True, None

            return False, f"Circuit half-open for {self.service_name}, awaiting test results"

    async def record_success(self) -> None:
        """Record a successful request."""
        async with self._lock:
            self._stats.total_requests += 1
            self._stats.successful_requests += 1
            self._stats.consecutive_successes += 1
            self._stats.consecutive_failures = 0
            self._stats.last_success_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                if self._stats.consecutive_successes >= self.config.half_open_requests:
                    self._transition_to(CircuitState.CLOSED)

    async def record_failure(self) -> None:
        """Record a failed request."""
        async with self._lock:
            self._stats.total_requests += 1
            self._stats.failed_requests += 1
            self._stats.consecutive_failures += 1
            self._stats.consecutive_successes = 0
            self._stats.last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open trips back to open
                self._transition_to(CircuitState.OPEN)
            elif self._state == CircuitState.CLOSED:
                if self._stats.consecutive_failures >= self.config.failure_threshold:
                    self._transition_to(CircuitState.OPEN)

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        old_state = self._state
        self._state = new_state
        self._stats.state_changed_at = time.monotonic()

        if new_state == CircuitState.CLOSED:
            self._stats.consecutive_failures = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_count = 0
            self._stats.consecutive_successes = 0

    async def reset(self) -> None:
        """Reset circuit breaker to initial state."""
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._stats = CircuitStats()
            self._half_open_count = 0

    def get_status(self) -> dict:
        """Get current circuit breaker status."""
        return {
            "service": self.service_name,
            "state": self._state.value,
            "stats": {
                "total_requests": self._stats.total_requests,
                "successful": self._stats.successful_requests,
                "failed": self._stats.failed_requests,
                "consecutive_failures": self._stats.consecutive_failures,
                "consecutive_successes": self._stats.consecutive_successes,
            },
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "recovery_timeout": self.config.recovery_timeout,
                "half_open_requests": self.config.half_open_requests,
            },
        }


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers."""

    def __init__(self):
        """Initialize the registry."""
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self, service_name: str, config: CircuitBreakerConfig
    ) -> CircuitBreaker:
        """Get existing circuit breaker or create new one."""
        async with self._lock:
            if service_name not in self._breakers:
                self._breakers[service_name] = CircuitBreaker(service_name, config)
            return self._breakers[service_name]

    async def get(self, service_name: str) -> Optional[CircuitBreaker]:
        """Get circuit breaker for service if exists."""
        async with self._lock:
            return self._breakers.get(service_name)

    async def get_all_status(self) -> dict[str, dict]:
        """Get status of all circuit breakers."""
        async with self._lock:
            return {name: cb.get_status() for name, cb in self._breakers.items()}

    async def reset_all(self) -> None:
        """Reset all circuit breakers."""
        async with self._lock:
            for breaker in self._breakers.values():
                await breaker.reset()


async def with_circuit_breaker(
    breaker: CircuitBreaker,
    func: Callable[[], Any],
    fallback: Optional[Callable[[], Any]] = None,
) -> Any:
    """
    Execute a function with circuit breaker protection.

    Args:
        breaker: Circuit breaker instance
        func: Async function to execute
        fallback: Optional fallback function if circuit is open

    Returns:
        Result of func or fallback

    Raises:
        CircuitOpenError: If circuit is open and no fallback provided
    """
    can_execute, reason = await breaker.can_execute()

    if not can_execute:
        if fallback:
            return await fallback() if asyncio.iscoroutinefunction(fallback) else fallback()
        raise CircuitOpenError(reason)

    try:
        result = await func() if asyncio.iscoroutinefunction(func) else func()
        await breaker.record_success()
        return result
    except Exception as e:
        await breaker.record_failure()
        raise


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass
