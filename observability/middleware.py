"""
observability/middleware.py — FastAPI 自动埋点中间件 (pure ASGI)

记录每个 HTTP 请求的:
  - 请求计数 (http_requests_total)
  - 延迟直方图 (http_request_duration_seconds)
  - 错误计数 (http_errors_total)

用法:
    from observability.middleware import add_observability_middleware
    add_observability_middleware(app)

实现备注:
    旧版基于 starlette.middleware.base.BaseHTTPMiddleware。
    BaseHTTPMiddleware 会把响应体重新包进 anyio TaskGroup（见 starlette#1438），
    SSE / StreamingResponse 在 chunk 间隙有概率被该 TaskGroup 取消，
    表现为 LangGraph 节点中途收到 CancelledError、前端 `network error`。
    哪怕 dispatch 里只是 `await call_next(request)` 直通也救不了 —— 包装本身就是问题。
    这里改写为纯 ASGI middleware，不进 BaseHTTPMiddleware 的 TaskGroup，
    SSE 路径与所有其它路径行为完全等同，不再有取消 race。
"""
from __future__ import annotations

import time

from fastapi import FastAPI

from observability.metrics import metrics


_SKIP_SUFFIXES = (".html", ".js", ".css", ".svg", ".png", ".ico", ".woff", ".woff2", ".map")
_SSE_PREFIXES = ("/api/v1/analyze", "/api/v1/health-check")


class ObservabilityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET")

        if path.startswith("/assets/") or path.endswith(_SKIP_SUFFIXES):
            await self.app(scope, receive, send)
            return
        if any(path.startswith(p) for p in _SSE_PREFIXES):
            await self.app(scope, receive, send)
            return

        metrics.counter("http_requests_total", method=method, path=path)

        t0 = time.perf_counter()
        status_box = {"code": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_box["code"] = message.get("status", 500)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            metrics.counter(
                "http_errors_total", method=method, path=path, status=status_box["code"]
            )
            raise
        finally:
            elapsed = time.perf_counter() - t0
            metrics.histogram(
                "http_request_duration_seconds", elapsed, method=method, path=path
            )
            if status_box["code"] >= 400:
                metrics.counter(
                    "http_errors_total",
                    method=method,
                    path=path,
                    status=status_box["code"],
                )


def add_observability_middleware(app: FastAPI):
    app.add_middleware(ObservabilityMiddleware)
