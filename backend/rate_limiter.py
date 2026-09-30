from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.config import settings


class InMemorySlidingWindowLimiter:
    """Thread-safe sliding window rate limiter."""

    def __init__(self) -> None:
        self._lock = Lock()
        # key -> list of timestamps
        self._history: dict[str, list[float]] = defaultdict(list)
        self._operations = 0

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> tuple[bool, int, int]:
        now = time.time()
        window_start = now - window_seconds

        with self._lock:
            self._operations += 1
            if self._operations % 512 == 0:
                self._cleanup_locked(now - 300)

            timestamps = self._history[key]
            # Prune older than window
            valid_timestamps = [ts for ts in timestamps if ts > window_start]
            self._history[key] = valid_timestamps

            count = len(valid_timestamps)
            if count < max_requests:
                valid_timestamps.append(now)
                remaining = max_requests - count - 1
                return True, remaining, 0
            else:
                oldest_in_window = valid_timestamps[0]
                retry_after = int(max(1, (oldest_in_window + window_seconds) - now))
                return False, 0, retry_after

    def cleanup(self, max_idle_seconds: int = 300) -> None:
        now = time.time()
        cutoff = now - max_idle_seconds
        with self._lock:
            self._cleanup_locked(cutoff)

    def _cleanup_locked(self, cutoff: float) -> None:
        keys_to_delete = [
            key for key, timestamps in self._history.items() if not timestamps or timestamps[-1] < cutoff
        ]
        for key in keys_to_delete:
            del self._history[key]


limiter = InMemorySlidingWindowLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        auth_limit: int = 12,
        general_limit: int = 150,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self.auth_limit = auth_limit
        self.general_limit = general_limit
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Ignore static assets, docs, health, options
        if (
            request.method == "OPTIONS"
            or path.startswith("/assets")
            or path.startswith("/favicon")
            or path in ("/health", "/ready", "/docs", "/openapi.json", "/redoc")
        ):
            return await call_next(request)

        # Identify client by IP
        forwarded = request.headers.get("x-forwarded-for")
        if settings.trust_proxy_headers and forwarded:
            client_ip = forwarded.split(",")[0].strip()
        elif request.client:
            client_ip = request.client.host
        else:
            client_ip = "unknown"

        is_auth_route = (
            path.startswith("/auth/login")
            or path.startswith("/auth/signup")
            or path.startswith("/auth/password")
        )
        max_requests = self.auth_limit if is_auth_route else self.general_limit
        rate_key = f"{client_ip}:{'auth' if is_auth_route else 'api'}"

        allowed, remaining, retry_after = limiter.is_allowed(
            rate_key, max_requests=max_requests, window_seconds=self.window_seconds
        )

        if not allowed:
            headers = {
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(max_requests),
                "X-RateLimit-Remaining": "0",
            }
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (f"Too many requests. Please slow down and try again in {retry_after} seconds.")
                },
                headers=headers,
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
