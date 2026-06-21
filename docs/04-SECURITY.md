# 04 — Security

[← Deployment](03-DEPLOYMENT.md) · [Next: Observability →](05-OBSERVABILITY.md)

## Threat model (summary)

| Surface | Threat | Control |
|---|---|---|
| Earth Engine credentials | Quota theft, account compromise | Service account, restricted IAM |
| Postgres `gis_engine` schema | Data leak across tenants | Row-level security (Phase 2) |
| Azure OpenAI key | Token theft | Cloud secret manager (Phase 8) |
| Voice transcripts in logs | PII exposure | Redaction middleware (Phase 8) |

## Secrets

- `.env.example` is the **only** env file in git.
- Pre-commit `gitleaks` scans for accidental commits of real secrets.
- Production secrets live in a managed secret store (cloud-native, chosen Phase 8).

Full threat model migrates from `biophysical-engine/docs/SECURITY_ARCHITECTURE.md` during Phase 7.