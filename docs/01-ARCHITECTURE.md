# 01 — Architecture

[← Executive Index](00-EXECUTIVE-INDEX.md) · [Next: API →](02-API.md)

## At a glance

```
Google Earth Engine ──► pipeline/ ──► PostgreSQL (gis_engine schema, RLS on)
                                          │
                                          ▼
                                     api/ (FastAPI) ──► ardalink-api
                                          │                (X-Tenant-ID + HMAC)
                                          ▼
                                     Azure OpenAI (optional)
```

## Layers

- **`pipeline/`** — GEE ingestion, grid reduction, scheduler, obstacle refresh.
- **`core_math/`** — livestock energy + nutrition formulas.
- **`geo/`** — grid math, routing, ward boundaries.
- **`db/`** — schema, seed data, connection client.
- **`api/`** — FastAPI routes and Pydantic models.
- **`ai/`** — Azure OpenAI client for analytical tasks.
- **`tenancy.py`** — multi-tenant context binding.

## Multi-tenant model (v0.2.0)

Every operational table in `gis_engine.*` carries a `tenant_id` column. Row-Level
Security policies enforce that queries only return rows whose `tenant_id`
matches the session variable `app.current_tenant_id`. The variable is bound
per-request by the `set_tenant()` context manager (see `ardalink_engine/tenancy.py`).

Trust chain:

1. Caller presents a JWT to `ardalink-api` (verified via shared secret or IdP).
2. `ardalink-api` extracts `tenant_id` claim, forwards the request here with
   `X-Tenant-ID` and a `X-Tenant-Sig` HMAC-SHA256 attestation.
3. This service verifies the attestation, then opens a DB transaction and
   issues `SET LOCAL app.current_tenant_id = '<id>'`.
4. RLS now rejects any row whose `tenant_id` differs.

If `TENANT_ATTESTATION_SECRET` is unset (dev only), attestation is bypassed
and any non-empty tenant id is accepted — never deploy without setting it.

Full architecture (with diagrams) migrates from legacy in Phase 7.