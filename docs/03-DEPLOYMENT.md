# 03 — Deployment

[← API](02-API.md) · [Next: Security →](04-SECURITY.md)

## Local

```bash
uv sync
cp .env.example .env  # fill in
uv run uvicorn ardalink_engine.main:app --reload --port 5001
```

## Docker (Phase 5)

```bash
docker build -t ardalink-engine:dev .
docker run --rm -p 5001:5001 --env-file .env ardalink-engine:dev
```

## Compose (Phase 5)

The engine runs as one service in the shared `infra/docker/compose.yml` —
alongside Postgres, Redis, `ardalink-api`, `ardalink-web`, and Caddy.

## Cloud

Cloud-agnostic by design. IaC (Terraform modules) is **deferred** until the
pilot validates the Compose model.