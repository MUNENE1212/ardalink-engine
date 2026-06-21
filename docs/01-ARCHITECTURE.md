# 01 — Architecture

[← Executive Index](00-EXECUTIVE-INDEX.md) · [Next: API →](02-API.md)

**Status**: stub — full content migrates from legacy `biophysical-engine/docs/ARCHITECTURE.md` during Phase 7 (docs rewrite).

## At a glance

```
Google Earth Engine ──► pipeline/ ──► PostgreSQL (gis_engine schema)
                                          │
                                          ▼
                                     api/ (FastAPI) ──► ardalink-api
                                          │
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

Full architecture (with diagrams) lands in Phase 7.