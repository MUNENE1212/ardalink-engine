# 07 — Runbooks

[← Costs](06-COSTS.md) · [Next: Team →](08-TEAM.md)

## On-call

| Severity | Response time | Who |
|---|---|---|
| SEV-1 (service down) | 15 min | Primary on-call |
| SEV-2 (degraded) | 1 hour | Primary on-call |
| SEV-3 (minor) | next business day | Triage queue |

## Common incidents

- **GEE quota exhausted** → degrade gracefully to cached baselines; alert.
- **DB connection storm** → scale pool, check for long-running queries.
- **Scheduler stuck** → restart process; verify `INGEST_NIGHT_ONLY` window.

## Backups

- PostgreSQL: daily base + WAL streaming. RPO 1h, RTO 4h.
- Restore drill: quarterly (procedure in `archive/RESTORE-DRILL.md`).

## Disaster recovery

See [Phase 0.5 backup](../archive/phase-0.5-backup.md) for pre-restructure snapshot
and full restore procedure.