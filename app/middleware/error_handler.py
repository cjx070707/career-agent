"""Global exception handlers — uniform error envelope for all unhandled exceptions.

All errors return:
  {"error": "<human-readable message>", "request_id": "<uuid>"}

Stack traces never leak to the client; they go to stdout for log aggregation.
"""
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "-")
    # Print full traceback server-side for debugging
    print(f"[ERROR] request_id={request_id} unhandled exception:")
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={
            "error": "服务器内部错误，请稍后重试",
            "request_id": request_id,
        },
    )


async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "-")
    return JSONResponse(
        status_code=400,
        content={
            "error": str(exc),
            "request_id": request_id,
        },
    )
