"""Schema definitions (DDL) for the ``gis_engine`` namespace.

Three core tables back the engine:

* ``isiolo_rangeland_matrix`` — directed ward-to-ward movement vectors.
* ``water_nodes``            — WPdx-aligned water point inventory.
* ``livestock_corridors``    — ILRI/ICPALD national livestock route geometries.
"""

from __future__ import annotations

from ..logging_config import get_logger
from .client import DatabaseClient

logger = get_logger("ardalink.db.schema")


def _ddl(schema: str) -> list[str]:
    return [
        f'''
        CREATE TABLE IF NOT EXISTS "{schema}".isiolo_rangeland_matrix (
            id                     SERIAL PRIMARY KEY,
            origin_zone            TEXT NOT NULL,
            destination_zone       TEXT NOT NULL,
            distance_km            DOUBLE PRECISION NOT NULL,
            elevation_gain_meters  DOUBLE PRECISION NOT NULL,
            energy_tax_index       DOUBLE PRECISION NOT NULL,
            vegetation_index_vci   DOUBLE PRECISION NOT NULL,
            water_availability_score DOUBLE PRECISION NOT NULL,
            UNIQUE (origin_zone, destination_zone)
        )
        ''',
        f'''
        CREATE TABLE IF NOT EXISTS "{schema}".water_nodes (
            id                  SERIAL PRIMARY KEY,
            wpdx_id             TEXT NOT NULL UNIQUE,
            name                TEXT NOT NULL,
            latitude            DOUBLE PRECISION NOT NULL,
            longitude           DOUBLE PRECISION NOT NULL,
            water_source_type   TEXT NOT NULL,
            functional_status   TEXT NOT NULL,
            last_verified_date  DATE,
            queue_time_index    INTEGER NOT NULL
        )
        ''',
        f'''
        CREATE TABLE IF NOT EXISTS "{schema}".livestock_corridors (
            id                  SERIAL PRIMARY KEY,
            route_id            TEXT NOT NULL UNIQUE,
            route_name          TEXT NOT NULL,
            geometry_path       TEXT NOT NULL,
            soil_friction_factor DOUBLE PRECISION NOT NULL,
            conflict_risk_score  DOUBLE PRECISION NOT NULL
        )
        ''',
        # Index supporting the fast origin/destination lookup performed by the API.
        f'''
        CREATE INDEX IF NOT EXISTS idx_rangeland_od
            ON "{schema}".isiolo_rangeland_matrix (origin_zone, destination_zone)
        ''',
        # --- Pre-computed environmental grid -------------------------------
        # Realised parameters of the built grid (single row, id=1). Persisting
        # these makes nearest-cell lookups correct even if config changes later.
        f'''
        CREATE TABLE IF NOT EXISTS "{schema}".grid_meta (
            id              INTEGER PRIMARY KEY DEFAULT 1,
            resolution_deg  DOUBLE PRECISION NOT NULL,
            resolution_m    DOUBLE PRECISION NOT NULL,
            south           DOUBLE PRECISION NOT NULL,
            west            DOUBLE PRECISION NOT NULL,
            north           DOUBLE PRECISION NOT NULL,
            east            DOUBLE PRECISION NOT NULL,
            nrows           INTEGER NOT NULL,
            ncols           INTEGER NOT NULL,
            cell_count      INTEGER NOT NULL,
            built_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT grid_meta_singleton CHECK (id = 1)
        )
        ''',
        # Static layers per cell: geometry plus slowly/never-changing environment
        # (terrain, the long-run NDVI min/mean/max envelope, urban mask).
        f'''
        CREATE TABLE IF NOT EXISTS "{schema}".grid_cells (
            cell_id         INTEGER PRIMARY KEY,
            row_idx         INTEGER NOT NULL,
            col_idx         INTEGER NOT NULL,
            latitude        DOUBLE PRECISION NOT NULL,
            longitude       DOUBLE PRECISION NOT NULL,
            elevation_m     DOUBLE PRECISION,
            slope_deg       DOUBLE PRECISION,
            ndvi_min        DOUBLE PRECISION,
            ndvi_max        DOUBLE PRECISION,
            ndvi_mean       DOUBLE PRECISION,
            urban_fraction  DOUBLE PRECISION,
            static_updated_at TIMESTAMPTZ
        )
        ''',
        # Dynamic layers per cell (refreshed on scheduled/triggered batches).
        f'''
        CREATE TABLE IF NOT EXISTS "{schema}".grid_dynamic (
            cell_id           INTEGER PRIMARY KEY
                REFERENCES "{schema}".grid_cells (cell_id) ON DELETE CASCADE,
            ndvi_now          DOUBLE PRECISION,
            vci               DOUBLE PRECISION,
            ndre              DOUBLE PRECISION,
            crude_protein_pct DOUBLE PRECISION,
            soil_moisture     DOUBLE PRECISION,
            temperature_c     DOUBLE PRECISION,
            humidity_pct      DOUBLE PRECISION,
            evapotranspiration_mm DOUBLE PRECISION
        )
        ''',
        # Per-layer freshness: each environmental layer is refreshed for ALL
        # cells at once, so a single timestamp per layer is the honest record of
        # how current that layer is. Never fake data — absence stays NULL.
        f'''
        CREATE TABLE IF NOT EXISTS "{schema}".grid_layer_meta (
            layer        TEXT PRIMARY KEY,
            source       TEXT,
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            cells_written INTEGER NOT NULL DEFAULT 0
        )
        ''',
        # --- Idempotent migrations for grids built by earlier versions ------
        # Add the long-run NDVI mean (added after the initial release).
        f'ALTER TABLE "{schema}".grid_cells ADD COLUMN IF NOT EXISTS ndvi_mean DOUBLE PRECISION',
        # Drop the prosopis mask: no Earth Engine product backs it, so the
        # column only ever held NULLs (no honest source to populate it).
        f'ALTER TABLE "{schema}".grid_cells DROP COLUMN IF EXISTS prosopis_fraction',
        # Which calendar month (1-12) the stored seasonal NDVI envelope
        # (grid_cells.ndvi_min/max/mean) was computed for. VCI is month-matched,
        # so this drives a "refresh the envelope when the month rolls over"
        # trigger. NULL until the first seasonal static ingest.
        f'ALTER TABLE "{schema}".grid_meta ADD COLUMN IF NOT EXISTS ndvi_envelope_month INTEGER',
    ]


def create_tables(client: DatabaseClient) -> None:
    """Create all engine tables and indexes (idempotent)."""
    client.ensure_schema()
    with client.connection() as conn:
        with conn.cursor() as cur:
            for statement in _ddl(client.schema):
                cur.execute(statement)
    logger.info("Engine tables ensured in schema '%s'", client.schema)
