"""Batch ingestion of environmental layers onto the Postgres grid.

This is the engine's data-factory. Rather than calling Earth Engine on every
request, heavy satellite/terrain reductions are run *ahead of time* over the
whole grid and the results stored in Postgres. Live queries then become cheap
nearest-cell lookups.

Three stages:

* :func:`build_grid` — create the grid lattice rows (geometry only). Pure SQL,
  server-side ``generate_series`` — fast even for millions of cells. Idempotent.
* :func:`ingest_static` — fill the slowly-changing layers (SRTM elevation +
  slope, the long-run MODIS NDVI envelope, ESA WorldCover urban fraction).
* :func:`ingest_layer` — refresh a single dynamic layer for every cell
  (``vegetation`` → NDVI/VCI from MODIS; ``protein`` → NDRE → crude protein from
  Sentinel-2). Records a per-layer freshness timestamp.

Earth Engine reductions are chunked: cells are grouped into batches of
``GRID_CHUNK_SIZE`` and reduced with a single ``reduceRegions`` + ``getInfo`` per
batch, respecting Earth Engine's per-call feature limits. Writes are bulk
``UPDATE ... FROM (VALUES ...)`` via ``execute_values``.

Honesty: nothing is fabricated. A layer that has never been ingested stays NULL
and simply has no row in ``grid_layer_meta``; callers report it as unavailable.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, Iterable

import psycopg2.extras

from ..config import settings
from ..core_math import nutrition
from ..db.client import db_client
from ..geo.grid import GridSpec, spec_from_config, spec_from_meta
from ..logging_config import get_logger
from .gee import ensure_initialized

logger = get_logger("ardalink.pipeline.grid_ingest")

# Earth Engine product ids.
SRTM_PRODUCT = "USGS/SRTMGL1_003"
MODIS_NDVI_PRODUCT = "MODIS/061/MOD13Q1"
MODIS_NDVI_BAND = "NDVI"
MODIS_NDVI_SCALE_M = 250
WORLDCOVER_PRODUCT = "ESA/WorldCover/v200"
WORLDCOVER_BUILTUP_CLASS = 50
SENTINEL2_PRODUCT = "COPERNICUS/S2_SR_HARMONIZED"
SENTINEL2_SCALE_M = 20
# Red-edge (B5, 705 nm, 20 m) and NIR (B8, 10 m) drive NDRE.
S2_REDEDGE_BAND = "B5"
S2_NIR_BAND = "B8"
# Recent window (days) for "current" composites.
CURRENT_WINDOW_DAYS = 90
S2_CLOUD_PCT_MAX = 40
# Climate: ERA5-Land daily air/dewpoint temperature + MODIS evapotranspiration.
ERA5_PRODUCT = "ECMWF/ERA5_LAND/DAILY_AGGR"
ERA5_SCALE_M = 1000
MOD16_PRODUCT = "MODIS/061/MOD16A2"
CLIMATE_WINDOW_DAYS = 30
# Soil moisture: SMAP L4 surface (008 supersedes the deprecated 007).
SMAP_PRODUCT = "NASA/SMAP/SPL4SMGP/008"
SMAP_SCALE_M = 9000
SOIL_WINDOW_DAYS = 15


# --------------------------------------------------------------------------
# Grid construction
# --------------------------------------------------------------------------
def build_grid(resolution_m: float | None = None) -> dict:
    """Create the grid lattice (geometry only) and persist its parameters.

    Server-side ``generate_series`` builds every cell in one statement. Existing
    cells are kept (``ON CONFLICT DO NOTHING``); call after changing resolution
    only on an empty grid (drop first via :func:`reset_grid`).
    """
    spec = spec_from_config(resolution_m)
    res_m = resolution_m if resolution_m is not None else settings.GRID_RESOLUTION_M
    schema = db_client.schema
    # Rebuild-safety: cell_id geometry depends on the grid spec, so refuse to
    # overwrite grid_meta on top of cells built at a *different* resolution.
    # The caller must reset_grid() first (the build-grid endpoint does on reset).
    existing = get_grid_meta()
    if existing is not None and (
        int(existing["ncols"]) != spec.ncols or int(existing["nrows"]) != spec.nrows
    ):
        raise RuntimeError(
            "Grid already built at a different resolution "
            f"({existing['nrows']}x{existing['ncols']} @ {existing['resolution_m']} m); "
            "reset the grid before rebuilding at a new resolution."
        )
    logger.info(
        "Building grid: %d x %d = %d cells at %.1f m (%.6f deg)",
        spec.nrows, spec.ncols, spec.cell_count, res_m, spec.resolution_deg,
    )
    with db_client.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'''
                INSERT INTO "{schema}".grid_cells
                    (cell_id, row_idx, col_idx, latitude, longitude)
                SELECT r * %(ncols)s + c, r, c,
                       %(south)s + (r + 0.5) * %(res)s,
                       %(west)s + (c + 0.5) * %(res)s
                FROM generate_series(0, %(nrows)s - 1) AS r,
                     generate_series(0, %(ncols)s - 1) AS c
                ON CONFLICT (cell_id) DO NOTHING
                ''',
                {
                    "ncols": spec.ncols,
                    "nrows": spec.nrows,
                    "south": spec.south,
                    "west": spec.west,
                    "res": spec.resolution_deg,
                },
            )
            cur.execute(
                f'''
                INSERT INTO "{schema}".grid_dynamic (cell_id)
                SELECT cell_id FROM "{schema}".grid_cells
                ON CONFLICT (cell_id) DO NOTHING
                '''
            )
            cur.execute(
                f'''
                INSERT INTO "{schema}".grid_meta
                    (id, resolution_deg, resolution_m, south, west, north, east,
                     nrows, ncols, cell_count, built_at)
                VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (id) DO UPDATE SET
                    resolution_deg = EXCLUDED.resolution_deg,
                    resolution_m = EXCLUDED.resolution_m,
                    south = EXCLUDED.south, west = EXCLUDED.west,
                    north = EXCLUDED.north, east = EXCLUDED.east,
                    nrows = EXCLUDED.nrows, ncols = EXCLUDED.ncols,
                    cell_count = EXCLUDED.cell_count, built_at = now()
                ''',
                (
                    spec.resolution_deg, res_m, spec.south, spec.west,
                    spec.north, spec.east, spec.nrows, spec.ncols, spec.cell_count,
                ),
            )
    logger.info("Grid build complete: %d cells", spec.cell_count)
    return {
        "cells": spec.cell_count,
        "nrows": spec.nrows,
        "ncols": spec.ncols,
        "resolution_m": res_m,
        "resolution_deg": spec.resolution_deg,
    }


def reset_grid() -> None:
    """Drop all grid rows (used before rebuilding at a different resolution)."""
    schema = db_client.schema
    with db_client.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f'TRUNCATE "{schema}".grid_dynamic, "{schema}".grid_cells')
            cur.execute(f'DELETE FROM "{schema}".grid_meta')
            cur.execute(f'DELETE FROM "{schema}".grid_layer_meta')


def get_grid_meta() -> dict | None:
    """Return the persisted grid parameters, or None if the grid is unbuilt."""
    return db_client.fetch_one(
        f'SELECT * FROM "{db_client.schema}".grid_meta WHERE id = 1'
    )


def _ingest_spec() -> GridSpec:
    """Grid spec from the *persisted* meta so ingestion matches the built cells.

    Earth Engine cell rectangles must use the resolution the grid was actually
    built with — not the current config, which may have drifted or been
    overridden at build time. Refuses to ingest before the grid is built.
    """
    meta = get_grid_meta()
    if meta is None:
        raise RuntimeError("Grid is not built; call build_grid first.")
    return spec_from_meta(meta)


# --------------------------------------------------------------------------
# Cell iteration / chunking helpers
# --------------------------------------------------------------------------
def _count_cells(bbox: tuple[float, float, float, float] | None) -> int:
    """Cheap COUNT of cells to ingest (optionally within a sub-bbox), for logging."""
    schema = db_client.schema
    if bbox is None:
        row = db_client.fetch_one(f'SELECT count(*) AS n FROM "{schema}".grid_cells')
    else:
        s, w, n, e = bbox
        row = db_client.fetch_one(
            f'''SELECT count(*) AS n FROM "{schema}".grid_cells
                WHERE latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s''',
            (s, n, w, e),
        )
    return int(row["n"]) if row else 0


def _iter_cell_chunks(
    bbox: tuple[float, float, float, float] | None, size: int
) -> Iterable[list[dict]]:
    """Stream grid cells in chunks of ``size``, keyset-paginated by ``cell_id``.

    The full 250 m grid is ~2M cells, so materializing every row in Python
    would risk OOM. Instead each chunk is a short, indexed ``cell_id > last``
    range scan on its own connection: only one chunk is resident at a time and
    no long-running read transaction is held open across the (slow) Earth
    Engine reductions between chunks.
    """
    schema = db_client.schema
    last_id = -1
    while True:
        if bbox is None:
            rows = db_client.fetch_all(
                f'''SELECT cell_id, row_idx, col_idx, latitude, longitude
                    FROM "{schema}".grid_cells
                    WHERE cell_id > %s
                    ORDER BY cell_id LIMIT %s''',
                (last_id, size),
            )
        else:
            s, w, n, e = bbox
            rows = db_client.fetch_all(
                f'''SELECT cell_id, row_idx, col_idx, latitude, longitude
                    FROM "{schema}".grid_cells
                    WHERE cell_id > %s
                      AND latitude BETWEEN %s AND %s
                      AND longitude BETWEEN %s AND %s
                    ORDER BY cell_id LIMIT %s''',
                (last_id, s, n, w, e, size),
            )
        if not rows:
            break
        yield rows
        last_id = int(rows[-1]["cell_id"])
        if len(rows) < size:
            break


def _cell_rectangles(cells: list[dict], spec: GridSpec):
    """Build an Earth Engine FeatureCollection of cell rectangles keyed by id."""
    import ee

    half = spec.resolution_deg / 2.0
    features = []
    for c in cells:
        lat, lon = float(c["latitude"]), float(c["longitude"])
        rect = ee.Geometry.Rectangle([lon - half, lat - half, lon + half, lat + half])
        features.append(ee.Feature(rect, {"cid": int(c["cell_id"])}))
    return ee.FeatureCollection(features)


def _reduce_chunk(image, cells: list[dict], spec: GridSpec, scale: int) -> dict[int, dict]:
    """Run a single mean reduceRegions over a chunk; return {cell_id: props}."""
    import ee

    fc = _cell_rectangles(cells, spec)
    reduced = image.reduceRegions(
        collection=fc, reducer=ee.Reducer.mean(), scale=scale
    )
    info = reduced.getInfo()
    out: dict[int, dict] = {}
    for feat in info.get("features", []):
        props = feat.get("properties", {})
        cid = props.get("cid")
        if cid is not None:
            out[int(cid)] = props
    return out


def _bulk_update(table: str, columns: list[str], rows: list[tuple]) -> int:
    """Bulk ``UPDATE table SET col=v.col... FROM (VALUES ...) WHERE cell_id``.

    ``rows`` are ``(cell_id, *values)`` aligned to ``columns``. Returns count.
    """
    if not rows:
        return 0
    schema = db_client.schema
    set_clause = ", ".join(f"{col} = v.{col}" for col in columns)
    col_list = ", ".join(["cell_id"] + columns)
    sql = (
        f'UPDATE "{schema}".{table} AS t SET {set_clause} '
        f'FROM (VALUES %s) AS v ({col_list}) '
        f'WHERE t.cell_id = v.cell_id'
    )
    with db_client.connection() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, sql, rows)
    return len(rows)


def _record_layer(layer: str, source: str, cells_written: int) -> None:
    schema = db_client.schema
    with db_client.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'''INSERT INTO "{schema}".grid_layer_meta
                        (layer, source, updated_at, cells_written)
                    VALUES (%s, %s, now(), %s)
                    ON CONFLICT (layer) DO UPDATE SET
                        source = EXCLUDED.source,
                        updated_at = now(),
                        cells_written = EXCLUDED.cells_written''',
                (layer, source, cells_written),
            )


# --------------------------------------------------------------------------
# Static ingestion
# --------------------------------------------------------------------------
def ingest_static(bbox: tuple[float, float, float, float] | None = None) -> dict:
    """Fill the static per-cell layers: terrain, NDVI envelope, urban fraction."""
    if not settings.gee_configured:
        from .gee import GEENotConfigured

        raise GEENotConfigured("Earth Engine is not configured; cannot ingest static layers.")
    ensure_initialized()
    import ee

    spec = _ingest_spec()
    total_cells = _count_cells(bbox)
    if total_cells == 0:
        raise RuntimeError("Grid is empty; call build_grid first.")

    # Composite image carrying every static band so one reduction fills them all.
    dem = ee.Image(SRTM_PRODUCT).select("elevation")
    slope = ee.Terrain.slope(dem).rename("slope")
    # SEASONAL NDVI envelope: the min/max/mean are computed over the SAME calendar
    # month across all years, not the whole archive. Isiolo is strongly seasonal,
    # so an all-time envelope conflates the dry/wet cycle with drought anomaly
    # (a normal dry month reads as "severe drought"). Month-matching is the
    # textbook VCI definition — is this March drier than a typical March — and it
    # also makes the reduction ~12x lighter. Persisted once here; VCI refreshes
    # reuse it (see _current_ndvi_image / the vegetation branch of ingest_layer).
    envelope_month = datetime.now(timezone.utc).month
    ndvi = (
        ee.ImageCollection(MODIS_NDVI_PRODUCT)
        .select(MODIS_NDVI_BAND)
        .filter(ee.Filter.calendarRange(envelope_month, envelope_month, "month"))
    )
    ndvi_min = ndvi.min().multiply(0.0001).rename("ndvi_min")
    ndvi_max = ndvi.max().multiply(0.0001).rename("ndvi_max")
    ndvi_mean = ndvi.mean().multiply(0.0001).rename("ndvi_mean")
    worldcover = ee.ImageCollection(WORLDCOVER_PRODUCT).first().select("Map")
    urban = worldcover.eq(WORLDCOVER_BUILTUP_CLASS).rename("urban")
    static_img = (
        dem.rename("elevation").addBands(slope).addBands(ndvi_min)
        .addBands(ndvi_max).addBands(ndvi_mean).addBands(urban)
    )

    columns = ["elevation_m", "slope_deg", "ndvi_min", "ndvi_max", "ndvi_mean",
               "urban_fraction", "static_updated_at"]
    total = 0
    started = time.time()
    for idx, chunk in enumerate(_iter_cell_chunks(bbox, settings.GRID_CHUNK_SIZE)):
        # Reduce at the coarsest native scale present (MODIS 250 m) for speed.
        props = _reduce_chunk(static_img, chunk, spec, MODIS_NDVI_SCALE_M)
        rows = []
        for c in chunk:
            cid = int(c["cell_id"])
            p = props.get(cid, {})
            rows.append((
                cid,
                p.get("elevation"),
                p.get("slope"),
                p.get("ndvi_min"),
                p.get("ndvi_max"),
                p.get("ndvi_mean"),
                p.get("urban"),
                None,  # static_updated_at set via SQL now() below
            ))
        # Use now() for the timestamp column directly.
        _bulk_update_static(rows)
        total += len(chunk)
        logger.info(
            "Static ingest chunk %d: %d/%d cells (%.1fs)",
            idx, total, total_cells, time.time() - started,
        )
    # Record static-layer freshness so it is transparently exposed alongside the
    # dynamic layers (SRTM terrain + MODIS NDVI envelope + ESA WorldCover urban).
    _record_layer("static", "SRTM+MODIS+WorldCover", total)
    # Stamp which calendar month this seasonal envelope represents, so the
    # scheduler re-runs the envelope when the month rolls over.
    _set_envelope_month(envelope_month)
    return {
        "cells_written": total,
        "ndvi_envelope_month": envelope_month,
        "layers": ["elevation", "slope", "ndvi_envelope", "urban"],
    }


def _set_envelope_month(month: int) -> None:
    """Persist the calendar month the stored seasonal NDVI envelope represents."""
    schema = db_client.schema
    with db_client.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'UPDATE "{schema}".grid_meta SET ndvi_envelope_month = %s WHERE id = 1',
                (month,),
            )


def _bulk_update_static(rows: list[tuple]) -> int:
    """Static update variant that stamps static_updated_at = now()."""
    if not rows:
        return 0
    schema = db_client.schema
    sql = (
        f'UPDATE "{schema}".grid_cells AS t SET '
        f'elevation_m = v.elevation_m, slope_deg = v.slope_deg, '
        f'ndvi_min = v.ndvi_min, ndvi_max = v.ndvi_max, ndvi_mean = v.ndvi_mean, '
        f'urban_fraction = v.urban_fraction, static_updated_at = now() '
        f'FROM (VALUES %s) AS v '
        f'(cell_id, elevation_m, slope_deg, ndvi_min, ndvi_max, ndvi_mean, urban_fraction, ts) '
        f'WHERE t.cell_id = v.cell_id'
    )
    with db_client.connection() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, sql, rows)
    return len(rows)


# --------------------------------------------------------------------------
# Dynamic layer ingestion
# --------------------------------------------------------------------------
def _current_ndvi_image():
    """Current-window MODIS NDVI only (single band: ``ndvi_now``).

    The VCI is no longer computed in Earth Engine. Recomputing the multi-year
    NDVI min/max envelope on every refresh was the heavy part — it reduced the
    whole archive at each cell. Instead the seasonal envelope is precomputed once
    by :func:`ingest_static` and stored per cell; this refresh only pulls the
    current NDVI and VCI is computed in Python against that stored envelope. So a
    vegetation refresh is just "pull today's greenness and compare", which is far
    cheaper and reuses work across refreshes.
    """
    import ee

    now_ms = int(time.time() * 1000)
    end = ee.Date(now_ms)
    start = end.advance(-CURRENT_WINDOW_DAYS, "day")
    return (
        ee.ImageCollection(MODIS_NDVI_PRODUCT)
        .select(MODIS_NDVI_BAND)
        .filterDate(start, end)
        .mean()
        .multiply(0.0001)
        .rename("ndvi_now")
    )


def _fetch_envelope(cell_ids: list[int]) -> dict[int, tuple]:
    """Stored seasonal NDVI envelope ``{cell_id: (ndvi_min, ndvi_max)}`` for cells."""
    if not cell_ids:
        return {}
    schema = db_client.schema
    rows = db_client.fetch_all(
        f'SELECT cell_id, ndvi_min, ndvi_max FROM "{schema}".grid_cells '
        f'WHERE cell_id = ANY(%s)',
        (cell_ids,),
    )
    return {int(r["cell_id"]): (r["ndvi_min"], r["ndvi_max"]) for r in rows}


def _protein_image():
    """Current Sentinel-2 NDRE (band: ndre) used to model crude protein."""
    import ee

    now_ms = int(time.time() * 1000)
    end = ee.Date(now_ms)
    start = end.advance(-CURRENT_WINDOW_DAYS, "day")
    coll = (
        ee.ImageCollection(SENTINEL2_PRODUCT)
        .filterDate(start, end)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", S2_CLOUD_PCT_MAX))
    )
    median = coll.median()
    nir = median.select(S2_NIR_BAND)
    rededge = median.select(S2_REDEDGE_BAND)
    ndre = nir.subtract(rededge).divide(nir.add(rededge)).rename("ndre")
    return ndre


def _climate_image():
    """ERA5-Land air conditions + MODIS evapotranspiration.

    Bands: ``temperature_c`` (mean 2 m air temperature, °C), ``humidity_pct``
    (relative humidity from air/dewpoint via the Magnus formula, %), and
    ``evapotranspiration_mm`` (MOD16A2 actual ET, converted to mm/day).
    """
    import ee

    now_ms = int(time.time() * 1000)
    end = ee.Date(now_ms)
    start = end.advance(-CLIMATE_WINDOW_DAYS, "day")
    era = (
        ee.ImageCollection(ERA5_PRODUCT)
        .filterDate(start, end)
        .select(["temperature_2m", "dewpoint_temperature_2m"])
        .mean()
    )
    t_c = era.select("temperature_2m").subtract(273.15).rename("temperature_c")
    td_c = era.select("dewpoint_temperature_2m").subtract(273.15).rename("td_c")
    # Magnus-formula relative humidity (%) from air and dewpoint temperature.
    rh = (
        t_c.addBands(td_c)
        .expression(
            "100 * (exp((17.625 * td) / (243.04 + td)) / exp((17.625 * t) / (243.04 + t)))",
            {"t": t_c.select("temperature_c"), "td": td_c.select("td_c")},
        )
        .clamp(0, 100)
        .rename("humidity_pct")
    )
    # MOD16A2 ET: 8-day total, band scale 0.1 mm; convert to mm/day.
    et = (
        ee.ImageCollection(MOD16_PRODUCT)
        .filterDate(start, end)
        .select("ET")
        .mean()
        .multiply(0.1 / 8.0)
        .rename("evapotranspiration_mm")
    )
    return t_c.addBands(rh).addBands(et)


def _soil_image():
    """SMAP L4 surface soil moisture (band: ``soil_moisture``, m3/m3)."""
    import ee

    now_ms = int(time.time() * 1000)
    end = ee.Date(now_ms)
    start = end.advance(-SOIL_WINDOW_DAYS, "day")
    return (
        ee.ImageCollection(SMAP_PRODUCT)
        .filterDate(start, end)
        .select("sm_surface")
        .mean()
        .rename("soil_moisture")
    )


def ingest_layer(
    layer: str, bbox: tuple[float, float, float, float] | None = None
) -> dict:
    """Refresh one dynamic layer for every cell. Returns counts + source.

    Supported layers:
    * ``vegetation`` → ``ndvi_now``, ``vci`` (MODIS MOD13Q1)
    * ``protein``    → ``ndre`` and modeled ``crude_protein_pct`` (Sentinel-2)
    * ``climate``    → ``temperature_c``, ``humidity_pct``, ``evapotranspiration_mm``
      (ERA5-Land + MOD16A2)
    * ``soil``       → ``soil_moisture`` (SMAP L4 surface)
    """
    if not settings.gee_configured:
        from .gee import GEENotConfigured

        raise GEENotConfigured(f"Earth Engine is not configured; cannot ingest '{layer}'.")
    ensure_initialized()

    spec = _ingest_spec()
    total_cells = _count_cells(bbox)
    if total_cells == 0:
        raise RuntimeError("Grid is empty; call build_grid first.")

    # Vegetation reuses the stored seasonal envelope: each chunk's (ndvi_min,
    # ndvi_max) is loaded here and VCI is computed in Python (no archive reduction).
    veg_envelope: dict[int, tuple] = {}

    if layer == "vegetation":
        image = _current_ndvi_image()
        columns = ["ndvi_now", "vci"]
        scale = MODIS_NDVI_SCALE_M
        source = MODIS_NDVI_PRODUCT

        def _row(cid: int, p: dict) -> tuple:
            # Single-band current-NDVI image: Earth Engine keys the reduceRegions
            # output column by the *reducer* ("mean"), not the band name.
            ndvi_now = p.get("ndvi_now", p.get("mean"))
            # VCI = where today sits in the SAME-MONTH historical [min, max], from
            # the precomputed envelope. Honest NULL when the envelope is missing
            # (cell never had a static ingest) or degenerate (max <= min).
            vci = None
            env = veg_envelope.get(cid)
            if ndvi_now is not None and env is not None:
                nmin, nmax = env
                if nmin is not None and nmax is not None and nmax > nmin:
                    vci = max(0.0, min(100.0, (ndvi_now - nmin) / (nmax - nmin) * 100.0))
            return (cid, ndvi_now, vci)

    elif layer == "protein":
        image = _protein_image()
        columns = ["ndre", "crude_protein_pct"]
        scale = SENTINEL2_SCALE_M
        source = SENTINEL2_PRODUCT

        def _row(cid: int, p: dict) -> tuple:
            # Earth Engine quirk: reduceRegions names the output column after the
            # *reducer* ("mean") for a single-band image, but after the *band*
            # for multi-band images. NDRE is a single band, so accept both.
            ndre = p.get("ndre", p.get("mean"))
            cp = nutrition.crude_protein_pct(ndre) if ndre is not None else None
            return (cid, ndre, cp)

    elif layer == "climate":
        image = _climate_image()
        columns = ["temperature_c", "humidity_pct", "evapotranspiration_mm"]
        scale = ERA5_SCALE_M
        source = f"{ERA5_PRODUCT}+{MOD16_PRODUCT}"

        def _row(cid: int, p: dict) -> tuple:
            return (
                cid,
                p.get("temperature_c"),
                p.get("humidity_pct"),
                p.get("evapotranspiration_mm"),
            )

    elif layer == "soil":
        image = _soil_image()
        columns = ["soil_moisture"]
        scale = SMAP_SCALE_M
        source = SMAP_PRODUCT

        def _row(cid: int, p: dict) -> tuple:
            # Single-band image: Earth Engine keys the column by reducer ("mean").
            sm = p.get("soil_moisture", p.get("mean"))
            return (cid, sm)

    else:
        raise ValueError(
            f"Unknown dynamic layer '{layer}'. "
            "Known: vegetation, protein, climate, soil"
        )

    total = 0
    written = 0
    started = time.time()
    for idx, chunk in enumerate(_iter_cell_chunks(bbox, settings.GRID_CHUNK_SIZE)):
        props = _reduce_chunk(image, chunk, spec, scale)
        if layer == "vegetation":
            # Load this chunk's stored seasonal envelope so _row can compute VCI.
            veg_envelope.clear()
            veg_envelope.update(_fetch_envelope([int(c["cell_id"]) for c in chunk]))
        rows = [_row(int(c["cell_id"]), props.get(int(c["cell_id"]), {})) for c in chunk]
        # Only update cells that received at least one non-id value.
        rows = [r for r in rows if any(v is not None for v in r[1:])]
        written += _bulk_update("grid_dynamic", columns, rows)
        total += len(chunk)
        logger.info(
            "Layer '%s' chunk %d: %d/%d cells scanned, %d written (%.1fs)",
            layer, idx, total, total_cells, written, time.time() - started,
        )

    _record_layer(layer, source, written)
    return {"layer": layer, "source": source, "cells_scanned": total, "cells_written": written}
