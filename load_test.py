#!/usr/bin/env python3
"""
Load testing script for the Rate-Limited API Gateway.

Demonstrates throughput, latency, and rate limiting behavior under load.
"""

import argparse
import asyncio
import statistics
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx


@dataclass
class LoadTestResult:
    """Results from a load test run."""
    total_requests: int = 0
    successful_requests: int = 0
    rate_limited_requests: int = 0
    failed_requests: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def duration_seconds(self) -> float:
        return self.end_time - self.start_time

    @property
    def requests_per_second(self) -> float:
        if self.duration_seconds == 0:
            return 0
        return self.total_requests / self.duration_seconds

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0
        return self.successful_requests / self.total_requests * 100

    @property
    def p50_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0
        return statistics.median(self.latencies_ms)

    @property
    def p99_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0
        sorted_latencies = sorted(self.latencies_ms)
        idx = int(len(sorted_latencies) * 0.99)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]

    @property
    def avg_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0
        return statistics.mean(self.latencies_ms)


class LoadTester:
    """Load tester for the API Gateway."""

    def __init__(
        self,
        base_url: str,
        num_clients: int = 10,
        requests_per_client: int = 100,
        concurrency: int = 50,
    ):
        """
        Initialize load tester.

        Args:
            base_url: Gateway base URL
            num_clients: Number of simulated clients
            requests_per_client: Requests per client
            concurrency: Max concurrent requests
        """
        self.base_url = base_url.rstrip("/")
        self.num_clients = num_clients
        self.requests_per_client = requests_per_client
        self.concurrency = concurrency
        self.semaphore = asyncio.Semaphore(concurrency)

    async def make_request(
        self,
        client: httpx.AsyncClient,
        client_id: str,
        endpoint: str,
    ) -> tuple[int, float]:
        """
        Make a single request.

        Returns:
            tuple of (status_code, latency_ms)
        """
        async with self.semaphore:
            start = time.perf_counter()
            try:
                response = await client.get(
                    f"{self.base_url}{endpoint}",
                    headers={"X-API-Key": client_id},
                    timeout=30.0,
                )
                latency_ms = (time.perf_counter() - start) * 1000
                return response.status_code, latency_ms
            except Exception as e:
                latency_ms = (time.perf_counter() - start) * 1000
                return 0, latency_ms

    async def run_client_load(
        self,
        client_id: str,
        endpoint: str,
        result: LoadTestResult,
    ) -> None:
        """Run load for a single simulated client."""
        async with httpx.AsyncClient() as client:
            for _ in range(self.requests_per_client):
                status, latency = await self.make_request(client, client_id, endpoint)

                result.total_requests += 1
                result.latencies_ms.append(latency)

                if status == 200:
                    result.successful_requests += 1
                elif status == 429:
                    result.rate_limited_requests += 1
                else:
                    result.failed_requests += 1

    async def run_load_test(
        self,
        endpoint: str = "/metrics",
        scenario: str = "standard",
    ) -> LoadTestResult:
        """
        Run the full load test.

        Args:
            endpoint: Endpoint to test
            scenario: Test scenario name

        Returns:
            LoadTestResult with aggregated results
        """
        result = LoadTestResult()
        result.start_time = time.time()

        print(f"\n{'='*60}")
        print(f"Load Test: {scenario}")
        print(f"{'='*60}")
        print(f"Base URL: {self.base_url}")
        print(f"Endpoint: {endpoint}")
        print(f"Clients: {self.num_clients}")
        print(f"Requests/client: {self.requests_per_client}")
        print(f"Concurrency: {self.concurrency}")
        print(f"Total requests: {self.num_clients * self.requests_per_client}")
        print(f"{'='*60}\n")

        # Create tasks for all clients
        tasks = [
            self.run_client_load(f"client-{i}", endpoint, result)
            for i in range(self.num_clients)
        ]

        # Run all client loads
        await asyncio.gather(*tasks)

        result.end_time = time.time()
        return result

    def print_results(self, result: LoadTestResult) -> None:
        """Print load test results."""
        print(f"\n{'='*60}")
        print("RESULTS")
        print(f"{'='*60}")
        print(f"Duration: {result.duration_seconds:.2f}s")
        print(f"Total Requests: {result.total_requests}")
        print(f"Successful: {result.successful_requests} ({result.success_rate:.1f}%)")
        print(f"Rate Limited: {result.rate_limited_requests}")
        print(f"Failed: {result.failed_requests}")
        print(f"\nThroughput: {result.requests_per_second:.2f} req/s")
        print(f"\nLatency:")
        print(f"  Average: {result.avg_latency_ms:.2f}ms")
        print(f"  P50: {result.p50_latency_ms:.2f}ms")
        print(f"  P99: {result.p99_latency_ms:.2f}ms")
        print(f"{'='*60}\n")


async def run_all_scenarios(base_url: str) -> None:
    """Run multiple load test scenarios."""

    # Scenario 1: Light load - should see mostly successful requests
    print("\n" + "="*60)
    print("SCENARIO 1: Light Load")
    print("="*60)
    tester = LoadTester(
        base_url=base_url,
        num_clients=5,
        requests_per_client=10,
        concurrency=10,
    )
    result = await tester.run_load_test(endpoint="/health", scenario="Light Load")
    tester.print_results(result)

    await asyncio.sleep(1)

    # Scenario 2: Heavy load - should trigger rate limiting
    print("\n" + "="*60)
    print("SCENARIO 2: Heavy Load (expect rate limiting)")
    print("="*60)
    tester = LoadTester(
        base_url=base_url,
        num_clients=20,
        requests_per_client=50,
        concurrency=100,
    )
    result = await tester.run_load_test(endpoint="/metrics", scenario="Heavy Load")
    tester.print_results(result)

    await asyncio.sleep(1)

    # Scenario 3: Burst traffic - sudden spike
    print("\n" + "="*60)
    print("SCENARIO 3: Burst Traffic")
    print("="*60)
    tester = LoadTester(
        base_url=base_url,
        num_clients=50,
        requests_per_client=20,
        concurrency=200,
    )
    result = await tester.run_load_test(endpoint="/metrics", scenario="Burst Traffic")
    tester.print_results(result)


async def compare_strategies(base_url: str) -> None:
    """Compare behavior across different client tiers."""
    print("\n" + "="*60)
    print("TIER COMPARISON TEST")
    print("="*60)

    async with httpx.AsyncClient() as client:
        # Set up different tier clients
        tiers = ["free", "basic", "premium", "enterprise"]

        for tier in tiers:
            client_id = f"tier-test-{tier}"
            # Set the tier
            await client.post(
                f"{base_url}/clients/{client_id}/tier",
                params={"tier": tier},
            )

        # Now test each tier
        results = {}
        for tier in tiers:
            client_id = f"tier-test-{tier}"
            successes = 0
            rate_limited = 0

            for _ in range(100):
                response = await client.get(
                    f"{base_url}/metrics",
                    headers={"X-API-Key": client_id},
                )
                if response.status_code == 200:
                    successes += 1
                elif response.status_code == 429:
                    rate_limited += 1

            results[tier] = {"successes": successes, "rate_limited": rate_limited}

        print("\nRequests per tier (100 requests each):")
        print("-" * 40)
        for tier, data in results.items():
            print(f"  {tier:12}: {data['successes']:3} OK, {data['rate_limited']:3} rate limited")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Load test the API Gateway")
    parser.add_argument(
        "--url",
        default="http://localhost:8080",
        help="Gateway base URL",
    )
    parser.add_argument(
        "--scenario",
        choices=["light", "heavy", "burst", "all", "compare"],
        default="all",
        help="Test scenario to run",
    )
    parser.add_argument(
        "--clients",
        type=int,
        default=10,
        help="Number of clients (for single scenarios)",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=100,
        help="Requests per client",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=50,
        help="Max concurrent requests",
    )

    args = parser.parse_args()

    if args.scenario == "all":
        asyncio.run(run_all_scenarios(args.url))
    elif args.scenario == "compare":
        asyncio.run(compare_strategies(args.url))
    else:
        tester = LoadTester(
            base_url=args.url,
            num_clients=args.clients,
            requests_per_client=args.requests,
            concurrency=args.concurrency,
        )
        result = asyncio.run(
            tester.run_load_test(scenario=args.scenario.title())
        )
        tester.print_results(result)


if __name__ == "__main__":
    main()
