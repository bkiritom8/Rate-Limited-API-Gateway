#!/usr/bin/env python3
"""
Run the Rate-Limited API Gateway.

Usage:
    python run_gateway.py [--host HOST] [--port PORT]
"""

import argparse
import uvicorn

from api_gateway.main import app
from api_gateway.config import get_config


def main():
    """Run the gateway server."""
    parser = argparse.ArgumentParser(description="Run the API Gateway")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    args = parser.parse_args()

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║            Rate-Limited API Gateway                          ║
╠══════════════════════════════════════════════════════════════╣
║  Starting server on {args.host}:{args.port}                            ║
║                                                              ║
║  Endpoints:                                                  ║
║    GET  /health          - Health check                      ║
║    GET  /ready           - Readiness check                   ║
║    GET  /metrics         - Metrics snapshot                  ║
║    GET  /metrics/latency - Latency percentiles               ║
║    GET  /circuit-breakers - Circuit breaker status           ║
║    POST /circuit-breakers/reset - Reset all breakers         ║
║    GET  /rate-limits/status/:id - Client rate limit status   ║
║    POST /clients/:id/tier - Set client tier                  ║
║    ANY  /api/*           - Proxy to upstream services        ║
║                                                              ║
║  Rate Limit Tiers:                                           ║
║    FREE:       1 req/s,   10 token bucket                    ║
║    BASIC:      5 req/s,   50 token bucket                    ║
║    PREMIUM:   20 req/s,  200 token bucket                    ║
║    ENTERPRISE:100 req/s, 1000 token bucket                   ║
╚══════════════════════════════════════════════════════════════╝
    """)

    uvicorn.run(
        "api_gateway.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
