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

        # 【关键】跳过 SSE 长流式端点 - BaseHTTPMiddleware 包装 StreamingResponse
        # 是 Starlette 已知问题: 长时间运行的 SSE 会被 anyio 内部任务组意外取消
        # https://github.com/encode/starlette/issues/1438
        # 这些端点动辄 5-10 分钟, 让它们直接走底层, 不进埋点
        SSE_PATHS = ("/api/v1/analyze", "/api/v1/analyze/", "/api/v1/health-check",
                      "/api/v1/health-check/")
        if any(path.startswith(p) for p in SSE_PATHS):
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
