# 05 — Observability

[← Security](04-SECURITY.md) · [Next: Costs →](06-COSTS.md)

## Logging

Structured JSON via `python-json-logger`. Correlation ID propagated via
`X-Request-ID` header from `ardalink-api`.

## Metrics

OpenTelemetry SDK → OTLP → backend (chosen in Phase 8).

Key gauges for the engine:
- `ardalink_engine.requests.total{service,route,status}`
- `ardalink_engine.request.duration_seconds{route}`
- `ardalink_engine.gee.calls.total{operation,status}`
- `ardalink_engine.scheduler.queue.depth`
- `ardalink_engine.db.connections.active`

## Tracing

Spans emitted for every FastAPI route + every Earth Engine call.
Trace context propagated from `ardalink-api` via W3C traceparent header.