# 06 — Costs

[← Observability](05-OBSERVABILITY.md) · [Next: Runbooks →](07-RUNBOOKS.md)

## Unit economics

| Tier | Households | Infra/month | Cost/herder |
|---|---|---|---|
| Pilot | 500 | ~$131 | ~$0.26 |
| County | 5,000 | ~$1,212 | ~$0.24 |
| Regional | 50,000 | ~$6,000 | ~$0.12 |

*With startup credits, first 12–18 months: $0.*

## Cost drivers for this service

- **Earth Engine API calls** (free for non-commercial use; quota applies)
- **Postgres storage** (grid + baselines scale with wards × months)
- **Compute** (FastAPI process + scheduler; trivially small for pilot)

Detailed cost model migrates from `biophysical-engine/docs/COSTS.md` in Phase 7.