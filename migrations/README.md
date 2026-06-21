# ArdaLink Engine — Database Migrations

SQL migrations applied manually with `psql`. Forward file `*.up.sql`,
rollback file `*.down.sql`, both reversible.

## Apply

```bash
export DATABASE_URL=postgresql://user:password@localhost:5432/ardalink

# Forward
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/0001_multitenant.up.sql

# Rollback
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/0001_multitenant.down.sql
```

## Naming

`NNNN_short_slug.up.sql` and `NNNN_short_slug.down.sql`. Never edit a
migration after it has been applied to a shared environment — write a new
one.

## Current

| # | Name | Purpose |
|---|---|---|
| 0001 | multitenant | Add `tenant_id` to every table, enable RLS, create `tenants` registry |

## CI

A drift check runs `psql --dry-run` against an ephemeral Postgres on every PR
(added in Phase 6). For now, apply migrations locally before merging.