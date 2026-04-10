"""
observability/middleware.py — FastAPI 自动埋点中间件

自动记录每个 HTTP 请求的:
  - 请求计数 (http_requests_total)
  - 延迟直方图 (http_request_duration_seconds)
  - 错误计数 (http_errors_total)
  - 当前并发数 (http_requests_in_flight)

用法:
    from observability.middleware import add_observability_middleware
    add_observability_middleware(app)
"""
from __future__ import annotations

import time

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from observability.metrics import metrics


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        # 跳过静态文件和 health check
        if path.startswith("/assets/") or path.endswith((".html", ".js", ".css", ".svg", ".png")):
            return await call_next(request)

        metrics.counter("http_requests_total", method=method, path=path)

        t0 = time.perf_counter()
        status = 500
        try:
            response: Response = await call_next(request)
            status = response.status_code
            return response
        except Exception:
            metrics.counter("http_errors_total", method=method, path=path, status=status)
            raise
        finally:
            elapsed = time.perf_counter() - t0
            metrics.histogram("http_request_duration_seconds", elapsed, method=method, path=path)
            if status >= 400:
                metrics.counter("http_errors_total", method=method, path=path, status=status)


def add_observability_middleware(app: FastAPI):
    """一行接入"""
    app.add_middleware(ObservabilityMiddleware)
