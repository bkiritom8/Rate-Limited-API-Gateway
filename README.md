# Rate-Limited API Gateway

A fully-featured, FastAPI-based API Gateway with rate limiting, circuit breaking, request routing, and observability. Designed to protect upstream services, enforce per-client rate limits, and provide detailed metrics for monitoring.

## Features

### Rate Limiting (Token Bucket)
- Per-client token bucket algorithm with configurable refill rates
- Four client tiers with different rate limits:

| Tier | Tokens/sec | Max Bucket |
|------|-----------|-----------|
| FREE | 1 | 10 |
| BASIC | 5 | 50 |
| PREMIUM | 20 | 200 |
| ENTERPRISE | 100 | 1000 |

- Endpoint-specific token costs for expensive operations
- Returns `Retry-After` headers when limits are exceeded

### Circuit Breaker
- Implements CLOSED → OPEN → HALF_OPEN states
- Protects upstream services from cascading failures
- Automatic recovery after configurable timeout

### Request Routing / Proxy
- Path-based routing via `/api/*` endpoints
- Forward headers and request data to upstream services
- Supports health checking for upstream endpoints

### Observability / Metrics
- Tracks request counts, latency percentiles (p50, p90, p95, p99), and error rates
- Exposes metrics via `/metrics` endpoints

## Project Structure

api_gateway/
├── __init__.py          - Package initializer
├── config.py            - Configuration management
├── models.py            - Pydantic models
├── rate_limiter.py      - Token Bucket Rate Limiter
├── circuit_breaker.py   - Circuit Breaker pattern
├── router.py            - Request Router/Proxy
├── metrics.py           - Observability/Metrics
├── middleware.py        - Rate limit middleware
└── main.py              - FastAPI application

tests/
├── test_rate_limiter.py
├── test_circuit_breaker.py
└── test_integration.py

load_test.py             - Load testing script
run_gateway.py           - Server runner
gateway_requirements.txt - Dependencies

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/metrics` | Metrics snapshot |
| GET | `/metrics/latency` | Latency percentiles |
| GET | `/circuit-breakers` | Circuit breaker status |
| POST | `/clients/{id}/tier` | Set client tier |
| ANY | `/api/*` | Proxy to upstream services |

## Installation

Clone the repository, create a virtual environment, and install dependencies:

git clone <repository-url>
cd <repository-directory>
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r gateway_requirements.txt

## Running the Gateway

Run using the included runner:

python run_gateway.py

Or directly with Uvicorn:

uvicorn api_gateway.main:app --reload --host 0.0.0.0 --port 8000

The gateway will be available at `http://localhost:8000`

## Testing

Run unit and integration tests:

pytest

Unit tests cover rate limiter, circuit breaker, and integration flows.

### Load Testing

Run `load_test.py` to simulate traffic and observe rate limiting and circuit breaker behavior:

python load_test.py

## Configuration

- **Client tiers** and token bucket parameters are configurable in `api_gateway/config.py`
- **Circuit breaker** thresholds and recovery times are configurable per upstream service
- **Metrics tracking** can be extended to include additional percentiles or custom metrics

## Example Usage

### Making a Request

curl -H "X-Client-ID: client-123" http://localhost:8000/api/users

### Setting Client Tier

curl -X POST http://localhost:8000/clients/client-123/tier \
  -H "Content-Type: application/json" \
  -d '{"tier": "PREMIUM"}'

### Viewing Metrics

curl http://localhost:8000/metrics
curl http://localhost:8000/metrics/latency

### Checking Circuit Breakers

curl http://localhost:8000/circuit-breakers

## License

MIT License

---

**Built with FastAPI** | **Production-Ready** | **Highly Configurable**