-- =============================================================================
-- Migration 0001 — Multi-tenant data model (rollback)
-- =============================================================================
--
-- Reverses `0001_multitenant.up.sql`:
--   1. Drops RLS policies and disables RLS on every gis_engine table.
--   2. Drops tenant_id indexes.
--   3. Drops tenant_id columns.
--   4. Drops the `tenants` registry.
--
-- Data in legacy rows is preserved (was backfilled to tenant_id = 'legacy' in
-- the forward migration). New rows from after the forward migration will
-- remain tagged 'legacy' — re-run the forward migration to re-establish
-- isolation.
--
-- Apply with:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/0001_multitenant.down.sql
--
-- =============================================================================

BEGIN;

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
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON gis_engine.%I', rec.tbl);
        EXECUTE format('ALTER TABLE gis_engine.%I NO FORCE ROW LEVEL SECURITY', rec.tbl);
        EXECUTE format('ALTER TABLE gis_engine.%I DISABLE ROW LEVEL SECURITY', rec.tbl);
        EXECUTE format('DROP INDEX IF EXISTS gis_engine.%I', rec.tbl || '_tenant_id_idx');
        EXECUTE format('ALTER TABLE gis_engine.%I DROP COLUMN IF EXISTS tenant_id', rec.tbl);
    END LOOP;
END
$$;

DROP TABLE IF EXISTS gis_engine.tenants CASCADE;

COMMIT;