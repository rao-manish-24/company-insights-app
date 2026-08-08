import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.request_context import clear_request_id, set_request_id

logger = logging.getLogger("companypulse.http")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Assign a request ID and log method, path, status, and duration."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        set_request_id(request_id)
        start = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "Unhandled error %s %s (%.1fms)",
                request.method,
                request.url.path,
                duration_ms,
            )
            clear_request_id()
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id

        # Skip noisy health checks at DEBUG only
        if request.url.path == "/api/health":
            logger.debug(
                "%s %s → %s (%.1fms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
        else:
            logger.info(
                "%s %s → %s (%.1fms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )

        clear_request_id()
        return response
