# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Phase 2: Multi-tenant data model
  - `migrations/0001_multitenant.up.sql` + `.down.sql` — adds `tenant_id` to every `gis_engine` table, creates `tenants` registry, enables RLS
  - `ardalink_engine/tenancy.py` — `set_tenant()` context manager and HMAC-SHA256 attestation helpers
  - `tests/test_tenancy.py` — unit tests for tenant binding and attestation
  - `TENANT_ATTESTATION_SECRET` env var documented in `.env.example`
  - `testcontainers[postgres]` added as dev dependency for future integration tests

### Added
- Initial scaffold from CTO restructure (Phase 1, 2026-06-21)
- 8-doc CTO navigation under `docs/`
- Ruff + mypy + pytest CI gating
- Dependabot for pip and github-actions
- Multi-tenant data model scaffold (arrives Phase 2)

## [0.1.0] - 2026-06-21

### Added
- FastAPI skeleton (`ardalink_engine/main.py`)
- `/health` endpoint
- Pytest smoke test
- pyproject.toml with uv lock baseline
- `.env.example` covering all runtime variables

### Notes
- Live source migrates from `MUNENE1212/biophysical-engine` in Phase 3.
- The 0.1.0 release is intentionally a thin skeleton so the migration is auditable.