# Security Policy

## Supported versions
Only the latest minor of `ardalink-engine` receives security updates.

## Reporting a vulnerability
Email **security@ardalink.local** (or open a private security advisory on GitHub).
Please do **not** file a public issue.

Include:
- Description of the vulnerability
- Reproduction steps
- Potential impact
- Your contact info

We aim to acknowledge within 2 business days and triage within 7 days.

## Threat model summary
- Satellite ingestion depends on third-party Google Earth Engine quotas.
- API endpoints are consumed by `ardalink-api` over private network only.
- Database connection string carries credentials — never commit `.env`.
- Voice transcripts may contain PII — see [docs/04-SECURITY.md](docs/04-SECURITY.md).

## Secret handling
- All credentials live in environment variables or cloud secret stores.
- `.env.example` lists every required variable with placeholder values.
- Pre-commit hooks scan for accidental commits of `.env`.