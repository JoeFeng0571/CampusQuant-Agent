"""
observability/ — 轻量级可观测性系统

SQLite 存储 + FastAPI 端点展示。不依赖 Prometheus/Grafana。
未来可迁移到 Prometheus 格式输出。

组件:
  metrics.py   — counter / histogram / gauge 采集
  tracing.py   — span context (简化版 OpenTelemetry)
  middleware.py — FastAPI 自动埋点中间件
"""
