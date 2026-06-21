# 00 — Executive Index

**Owner**: CTO  ·  **Audience**: Executive, Board, Engineering Leads  ·  **Read**: 5 min  ·  **Next review**: Q3 2026

---

## Where we are

ArdaLink Engine is the **biophysical brain** of the ArdaLink platform. It ingests
satellite observations, scores livestock journeys, and exposes a small, focused
HTTP API to `ardalink-api`.

| Component | Status | Notes |
|---|---|---|
| FastAPI service | ✅ Skeleton | Live source migrates in Phase 3 |
| Earth Engine pipeline | ⏳ Migrating | From legacy `biophysical-engine` |
| Grid storage (PostgreSQL `gis_engine`) | ⏳ Migrating | |
| Multi-tenant schema | 🔜 Phase 2 | Required before pilot expansion |
| CI gating | ✅ Configured | Ruff + mypy + pytest enforced |
| Container image | 🔜 Phase 5 | Distroless Python 3.12 |

## What we ship

One Python service answering four kinds of questions about a place in Isiolo:
**how green is it**, **how stressful is the climate**, **how much energy will
this journey cost**, **how risky is this path**.

## Top risks

1. **GEE quota change** — single-vendor dependency on Google Earth Engine.
   *Mitigation*: cache pixel grids locally; baseline data works offline.
2. **Multi-tenant data model not yet shipped** — required for multi-ward pilot.
   *Owner*: Phase 2.
3. **No integration test suite** — contract tests against `ardalink-api`
   arrive in Phase 6.

## Top decisions needed

1. Confirm cloud target (deferred per plan — Compose-only until pilot validates).
2. Confirm multi-tenant key strategy (shared JWT vs. per-tenant API keys).
3. Confirm pilot ward list (drives seed data).

## What's next

| When | Milestone | KPI |
|---|---|---|
| Week 1 | Phase 3 code migration | v0.2.0 released |
| Week 2 | Multi-tenant schema | All tables carry `tenant_id` |
| Week 4 | Contract tests vs ardalink-api green | No regression in pilot flow |
| Q3 2026 | Multi-ward pilot | 500 households, 3 wards |