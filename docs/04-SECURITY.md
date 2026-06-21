# 04 — Security

[← Deployment](03-DEPLOYMENT.md) · [Next: Observability →](05-OBSERVABILITY.md)

## Threat model (summary)

| Surface | Threat | Control |
|---|---|---|
| Earth Engine credentials | Quota theft, account compromise | Service account, restricted IAM |
| Postgres `gis_engine` schema | Cross-tenant data leak | Row-Level Security (v0.2.0) |
| Tenant id spoofing | Upstream bug allows caller to choose tenant | HMAC-SHA256 attestation header |
| Azure OpenAI key | Token theft | Cloud secret manager (Phase 8) |
| Voice transcripts in logs | PII exposure | Redaction middleware (Phase 8) |

## Multi-tenant isolation (v0.2.0)

Every query on this service is bound to a tenant via `ardalink_engine.tenancy.set_tenant()`.
Postgres RLS policies (see `migrations/0001_multitenant.up.sql`) reject any row whose
`tenant_id` does not match the session variable. The `TENANT_ATTESTATION_SECRET` env var
gates this in production — never run with an empty value.

## Secrets

- `.env.example` is the **only** env file in git.
- Pre-commit `gitleaks` scans for accidental commits of real secrets.
- Production secrets live in a managed secret store (cloud-native, chosen Phase 8).

Full threat model migrates from `biophysical-engine/docs/SECURITY_ARCHITECTURE.md` during Phase 7.