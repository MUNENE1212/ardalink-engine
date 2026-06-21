# 02 — API

[← Architecture](01-ARCHITECTURE.md) · [Next: Deployment →](03-DEPLOYMENT.md)

## Interactive docs
- Swagger UI: `http://localhost:5001/docs`
- ReDoc: `http://localhost:5001/redoc`

## Endpoints (v0.1.0)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness probe |
| GET | `/docs` | Swagger UI |
| GET | `/redoc` | ReDoc UI |

## Contract with `ardalink-api`

The canonical OpenAPI contract lives at
[`MUNENE1212/ardalink-api/lib/api-spec/openapi.yaml`](https://github.com/MUNENE1212/ardalink-api/blob/main/lib/api-spec/openapi.yaml).
This service consumes the generated Pydantic models (Phase 3).