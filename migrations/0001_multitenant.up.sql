-- =============================================================================
-- Migration 0001 — Multi-tenant data model (forward)
-- =============================================================================
--
-- This migration prepares every operational table in the `gis_engine` schema
-- for multi-ward expansion by:
--   1. Adding a `tenant_id` column to every existing table.
--   2. Creating a `tenants` registry table.
--   3. Enabling PostgreSQL Row-Level Security (RLS) on every scoped table
--      with a policy keyed off the session variable `app.current_tenant_id`.
--   4. Backfilling legacy rows to a default tenant (`legacy`) so the
--      migration is reversible by data, not destructive.
--
-- Reversible by `0001_multitenant.down.sql` in the same directory.
--
-- Apply with:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/0001_multitenant.up.sql
--
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. Tenants registry (authoritative list of wards/regions onboarded).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gis_engine.tenants (
    tenant_id     TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    region        TEXT NOT NULL,
    bbox_s        DOUBLE PRECISION,
    bbox_w        DOUBLE PRECISION,
    bbox_n        DOUBLE PRECISION,
    bbox_e        DOUBLE PRECISION,
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed the pilot tenants (multi-ward per CTO plan).
INSERT INTO gis_engine.tenants (tenant_id, display_name, region, bbox_s, bbox_w, bbox_n, bbox_e)
VALUES
    ('bula-pesa',    'Bula Pesa Ward',   'Isiolo County', -0.6, 36.5, 2.9, 39.6),
    ('garbatulla',   'Garbatulla Ward',  'Isiolo County', -0.6, 36.5, 2.9, 39.6),
    ('merti',        'Merti Ward',       'Isiolo County', -0.6, 36.5, 2.9, 39.6),
    ('legacy',       'Legacy data',      'Pre-multi-tenant', NULL, NULL, NULL, NULL)
ON CONFLICT (tenant_id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 2. Add tenant_id to every existing gis_engine table.
-- -----------------------------------------------------------------------------
-- The list mirrors the schema created by `ardalink_engine.db.schema.create_tables`.
-- Adjust here if upstream schema diverges.

DO $$
DECLARE
    rec RECORD;
BEGIN
    FOR rec IN
        SELECT c.relname AS tbl
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'gis_engine'
          AND c.relkind = 'r'
          AND c.relname NOT IN ('tenants')
    LOOP
        EXECUTE format(
            'ALTER TABLE gis_engine.%I ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT %L',
            rec.tbl,
            'legacy'
        );
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON gis_engine.%I (tenant_id)',
            rec.tbl || '_tenant_id_idx',
            rec.tbl
        );
    END LOOP;
END
$$;

-- -----------------------------------------------------------------------------
-- 3. Row-Level Security — app sets `SET LOCAL app.current_tenant_id = '<id>'`
--    at the start of every connection / transaction; RLS policies below enforce
--    that SELECT/INSERT/UPDATE/DELETE never crosses tenant boundaries.
-- -----------------------------------------------------------------------------

DO $$
DECLARE
    rec RECORD;
BEGIN
    FOR rec IN
        SELECT c.relname AS tbl
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'gis_engine'
          AND c.relkind = 'r'
          AND c.relname NOT IN ('tenants')
    LOOP
        EXECUTE format('ALTER TABLE gis_engine.%I ENABLE ROW LEVEL SECURITY', rec.tbl);
        EXECUTE format('ALTER TABLE gis_engine.%I FORCE ROW LEVEL SECURITY', rec.tbl);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON gis_engine.%I', rec.tbl);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON gis_engine.%I '
            'USING (tenant_id = current_setting(''app.current_tenant_id'', TRUE)) '
            'WITH CHECK (tenant_id = current_setting(''app.current_tenant_id'', TRUE))',
            rec.tbl
        );
    END LOOP;
END
$$;

COMMIT;

-- =============================================================================
-- Verification (read-only — does not run by default):
-- =============================================================================
--
--   SELECT tablename, rowsecurity, forcerowsecurity
--   FROM pg_tables WHERE schemaname = 'gis_engine';
--
-- Expected: rowsecurity = TRUE, forcerowsecurity = TRUE for every table
-- except `tenants` (which is the registry, not the operational data).
--