"""Tests for the Circuit Breaker."""

import asyncio
import pytest
import time

from api_gateway.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitState,
    CircuitOpenError,
    with_circuit_breaker,
)
from api_gateway.models import CircuitBreakerConfig


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    @pytest.fixture
    def config(self):
        """Create test circuit breaker configuration."""
        return CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=0.5,
            half_open_requests=2,
        )

    @pytest.fixture
    def circuit(self, config):
        """Create circuit breaker instance."""
        return CircuitBreaker("test_service", config)

    @pytest.mark.asyncio
    async def test_initial_state_closed(self, circuit):
        """Circuit starts in closed state."""
        assert circuit.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_allows_requests_when_closed(self, circuit):
        """Requests are allowed when circuit is closed."""
        can_execute, reason = await circuit.can_execute()
        assert can_execute is True
        assert reason is None

    @pytest.mark.asyncio
    async def test_opens_after_failures(self, circuit):
        """Circuit opens after threshold failures."""
        # Record failures
        for _ in range(3):
            await circuit.record_failure()

        assert circuit.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_rejects_when_open(self, circuit):
        """Requests are rejected when circuit is open."""
        # Open the circuit
        for _ in range(3):
            await circuit.record_failure()

        can_execute, reason = await circuit.can_execute()
        assert can_execute is False
        assert "Circuit open" in reason

    @pytest.mark.asyncio
    async def test_half_open_after_timeout(self, circuit):
        """Circuit transitions to half-open after recovery timeout."""
        # Open the circuit
        for _ in range(3):
            await circuit.record_failure()

        assert circuit.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(0.6)

        # Check should trigger half-open
        can_execute, _ = await circuit.can_execute()
        assert can_execute is True
        assert circuit.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_closes_after_half_open_successes(self, circuit):
        """Circuit closes after successful half-open requests."""
        # Open the circuit
        for _ in range(3):
            await circuit.record_failure()

        # Wait for recovery timeout
        await asyncio.sleep(0.6)

        # Trigger half-open
        await circuit.can_execute()
        assert circuit.state == CircuitState.HALF_OPEN

        # Record successful requests
        await circuit.record_success()
        await circuit.record_success()

        assert circuit.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_reopens_on_half_open_failure(self, circuit):
        """Circuit reopens on failure during half-open."""
        # Open the circuit
        for _ in range(3):
            await circuit.record_failure()

        # Wait for recovery timeout
        await asyncio.sleep(0.6)

        # Trigger half-open
        await circuit.can_execute()
        assert circuit.state == CircuitState.HALF_OPEN

        # Record failure
        await circuit.record_failure()

        assert circuit.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self, circuit):
        """Successful requests reset consecutive failure count."""
        await circuit.record_failure()
        await circuit.record_failure()
        await circuit.record_success()

        # Failures should be reset
        assert circuit.stats.consecutive_failures == 0

        # One more failure shouldn't open circuit
        await circuit.record_failure()
        assert circuit.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_reset(self, circuit):
        """Can reset circuit to initial state."""
        for _ in range(3):
            await circuit.record_failure()

        assert circuit.state == CircuitState.OPEN

        await circuit.reset()

        assert circuit.state == CircuitState.CLOSED
        assert circuit.stats.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_get_status(self, circuit):
        """Can get circuit breaker status."""
        await circuit.record_success()
        await circuit.record_failure()

        status = circuit.get_status()

        assert status["service"] == "test_service"
        assert status["state"] == "closed"
        assert status["stats"]["total_requests"] == 2
        assert status["stats"]["successful"] == 1
        assert status["stats"]["failed"] == 1


class TestCircuitBreakerRegistry:
    """Tests for CircuitBreakerRegistry class."""

    @pytest.fixture
    def registry(self):
        """Create registry instance."""
        return CircuitBreakerRegistry()

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return CircuitBreakerConfig(failure_threshold=5)

    @pytest.mark.asyncio
    async def test_get_or_create(self, registry, config):
        """Creates circuit breaker if not exists."""
        circuit = await registry.get_or_create("service1", config)
        assert circuit is not None
        assert circuit.service_name == "service1"

    @pytest.mark.asyncio
    async def test_returns_same_instance(self, registry, config):
        """Returns same circuit breaker instance."""
        circuit1 = await registry.get_or_create("service1", config)
        circuit2 = await registry.get_or_create("service1", config)
        assert circuit1 is circuit2

    @pytest.mark.asyncio
    async def test_get_all_status(self, registry, config):
        """Can get status of all circuit breakers."""
        await registry.get_or_create("service1", config)
        await registry.get_or_create("service2", config)

        all_status = await registry.get_all_status()

        assert "service1" in all_status
        assert "service2" in all_status

    @pytest.mark.asyncio
    async def test_reset_all(self, registry, config):
        """Can reset all circuit breakers."""
        circuit1 = await registry.get_or_create("service1", config)
        circuit2 = await registry.get_or_create("service2", config)

        # Open both circuits
        for _ in range(5):
            await circuit1.record_failure()
            await circuit2.record_failure()

        assert circuit1.state == CircuitState.OPEN
        assert circuit2.state == CircuitState.OPEN

        await registry.reset_all()

        assert circuit1.state == CircuitState.CLOSED
        assert circuit2.state == CircuitState.CLOSED


class TestWithCircuitBreaker:
    """Tests for with_circuit_breaker helper."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return CircuitBreakerConfig(failure_threshold=2)

    @pytest.fixture
    def circuit(self, config):
        """Create circuit breaker instance."""
        return CircuitBreaker("test", config)

    @pytest.mark.asyncio
    async def test_executes_function(self, circuit):
        """Executes function when circuit is closed."""
        async def success_func():
            return "success"

        result = await with_circuit_breaker(circuit, success_func)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_records_success(self, circuit):
        """Records success after function completes."""
        async def success_func():
            return "ok"

        await with_circuit_breaker(circuit, success_func)
        assert circuit.stats.successful_requests == 1

    @pytest.mark.asyncio
    async def test_records_failure_on_exception(self, circuit):
        """Records failure when function raises exception."""
        async def failing_func():
            raise ValueError("error")

        with pytest.raises(ValueError):
            await with_circuit_breaker(circuit, failing_func)

        assert circuit.stats.failed_requests == 1

    @pytest.mark.asyncio
    async def test_uses_fallback_when_open(self, circuit):
        """Uses fallback when circuit is open."""
        # Open circuit
        for _ in range(2):
            await circuit.record_failure()

        async def primary():
            return "primary"

        async def fallback():
            return "fallback"

        result = await with_circuit_breaker(circuit, primary, fallback)
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_raises_when_open_no_fallback(self, circuit):
        """Raises CircuitOpenError when open and no fallback."""
        for _ in range(2):
            await circuit.record_failure()

        async def primary():
            return "primary"

        with pytest.raises(CircuitOpenError):
            await with_circuit_breaker(circuit, primary)
