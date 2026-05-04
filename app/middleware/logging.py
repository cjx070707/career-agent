"""Structured request/response logging middleware.

Logs every request with method, path, status code, latency, and request_id.
Output goes to stdout as JSON lines — compatible with any log aggregator.
"""
import json
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        t0 = time.monotonic()
        response = await call_next(request)
        latency_ms = int((time.monotonic() - t0) * 1000)

        request_id = getattr(request.state, "request_id", "-")
        log = {
            "event": "http_request",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "latency_ms": latency_ms,
            "client": request.client.host if request.client else "-",
        }
        print(json.dumps(log, ensure_ascii=False), flush=True)
        return response
