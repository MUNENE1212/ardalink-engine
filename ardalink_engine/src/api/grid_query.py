"""Query services backed by the pre-computed grid.

These endpoints never call Earth Engine. They resolve a GPS point (or a journey
between points) to the nearest grid cell(s) — pure arithmetic plus an integer
primary-key lookup — and read the stored environmental layers. Every figure is
returned with its provenance and per-layer freshness so consumers can see how
current the data is and which values are modeled proxies versus measured.
"""

from __future__ import annotations

import math

from ..core_math import nutrition
from ..core_math.energy import assess_feed_gap, resolve_profile
from ..db.client import db_client
from ..geo.grid import GridSpec, spec_from_meta
from ..geo.routing import route_around
from ..geo.wards import WARDS, haversine_km
from ..logging_config import get_logger
from ..pipeline import obstacles as obstacle_source

logger = get_logger("ardalink.api.grid_query")


class GridNotBuilt(RuntimeError):
    """Raised when a query is attempted before the grid has been built."""


def _load_spec() -> GridSpec:
    meta = db_client.fetch_one(f'SELECT * FROM "{db_client.schema}".grid_meta WHERE id = 1')
    if meta is None:
        raise GridNotBuilt("Environmental grid has not been built yet (call /api/v1/ingest/build-grid).")
    return spec_from_meta(meta)


def _layer_freshness() -> dict[str, dict]:
    rows = db_client.fetch_all(
        f'SELECT layer, source, updated_at, cells_written FROM "{db_client.schema}".grid_layer_meta'
    )
    out: dict[str, dict] = {}
    for r in rows:
        ts = r["updated_at"]
        out[r["layer"]] = {
            "source": r["source"],
            "updated_at": ts.isoformat() if ts is not None else None,
            "cells_written": r["cells_written"],
        }
    return out


_CELL_SELECT = (
    '''SELECT c.cell_id, c.row_idx, c.col_idx, c.latitude, c.longitude,
              c.elevation_m, c.slope_deg, c.ndvi_min, c.ndvi_max, c.ndvi_mean,
              c.urban_fraction, c.static_updated_at,
              d.ndvi_now, d.vci, d.ndre, d.crude_protein_pct,
              d.soil_moisture, d.temperature_c, d.humidity_pct,
              d.evapotranspiration_mm
       FROM "{schema}".grid_cells c
       LEFT JOIN "{schema}".grid_dynamic d ON d.cell_id = c.cell_id'''
)


def _fetch_cell(cell_id: int) -> dict | None:
    return db_client.fetch_one(
        _CELL_SELECT.format(schema=db_client.schema) + " WHERE c.cell_id = %s",
        (cell_id,),
    )


def _fetch_cells(cell_ids: set[int]) -> dict[int, dict]:
    """Batch-load many cells in a single query, keyed by ``cell_id``.

    A journey samples its corridor densely (every traversed cell), so fetching
    each cell with its own round-trip would be slow. One ``= ANY(...)`` query
    keeps even a fine, county-long corridor cheap.
    """
    if not cell_ids:
        return {}
    rows = db_client.fetch_all(
        _CELL_SELECT.format(schema=db_client.schema) + " WHERE c.cell_id = ANY(%s)",
        (list(cell_ids),),
    )
    return {int(r["cell_id"]): r for r in rows}


def _forage_block(cell: dict) -> dict:
    """Derive forage quantity/quality figures from a cell's stored layers."""
    ndvi_now = cell.get("ndvi_now")
    vci = cell.get("vci")
    cp = cell.get("crude_protein_pct")
    biomass = nutrition.biomass_kg_per_ha(ndvi_now) if ndvi_now is not None else None
    return {
        "ndvi_now": _round(ndvi_now, 3),
        "vci": _round(vci, 1),
        "ndre": _round(cell.get("ndre"), 3),
        "crude_protein_pct": _round(cp, 1),
        "biomass_kg_per_ha": biomass,
        "availability_factor": nutrition.availability_factor(vci, biomass),
        "modeled_fields": ["biomass_kg_per_ha", "crude_protein_pct"],
    }


def _conditions_block(cell: dict) -> dict:
    """Current weather/soil conditions stored for a cell (measured GEE layers)."""
    return {
        "soil_moisture_m3_m3": _round(cell.get("soil_moisture"), 3),
        "temperature_c": _round(cell.get("temperature_c"), 1),
        "humidity_pct": _round(cell.get("humidity_pct"), 1),
        "evapotranspiration_mm_per_day": _round(cell.get("evapotranspiration_mm"), 2),
    }


def _round(value, ndigits):
    return round(value, ndigits) if value is not None else None


def _coverage(cell: dict) -> str:
    """Honest coverage flag for a cell's dynamic layers."""
    has_veg = cell.get("vci") is not None or cell.get("ndvi_now") is not None
    has_protein = cell.get("crude_protein_pct") is not None
    if has_veg and has_protein:
        return "full"
    if has_veg or has_protein:
        return "partial"
    return "static_only"


def point_conditions(lat: float, lon: float) -> dict:
    """Return the environmental conditions of the grid cell nearest a GPS point."""
    spec = _load_spec()
    in_grid = spec.contains(lat, lon)
    cell_id, row, col = spec.nearest_cell(lat, lon)
    cell = _fetch_cell(cell_id)
    if cell is None:
        raise GridNotBuilt("Nearest cell missing from grid; rebuild the grid.")

    cell_lat, cell_lon = float(cell["latitude"]), float(cell["longitude"])
    return {
        "query": {"latitude": lat, "longitude": lon, "within_grid": in_grid},
        "cell": {
            "cell_id": cell_id,
            "row": row,
            "col": col,
            "latitude": cell_lat,
            "longitude": cell_lon,
            "distance_to_cell_center_km": round(
                haversine_km(lat, lon, cell_lat, cell_lon), 4
            ),
            "resolution_m": round(spec.resolution_deg * 111_320.0, 1),
        },
        "terrain": {
            "elevation_m": _round(cell.get("elevation_m"), 1),
            "slope_deg": _round(cell.get("slope_deg"), 2),
        },
        "vegetation_envelope": {
            "ndvi_min": _round(cell.get("ndvi_min"), 3),
            "ndvi_max": _round(cell.get("ndvi_max"), 3),
            "ndvi_mean": _round(cell.get("ndvi_mean"), 3),
        },
        "forage": _forage_block(cell),
        "current_conditions": _conditions_block(cell),
        "drought_status": nutrition.drought_status(cell.get("vci")),
        "masks": {
            "urban_fraction": _round(cell.get("urban_fraction"), 3),
        },
        "coverage": _coverage(cell),
        "freshness": _layer_freshness(),
    }


_CELL_LAYER_FIELDS = (
    "elevation_m",
    "slope_deg",
    "ndvi_mean",
    "ndvi_now",
    "vci",
    "crude_protein_pct",
    "soil_moisture",
    "temperature_c",
    "humidity_pct",
    "evapotranspiration_mm",
    "urban_fraction",
)

_CELL_ROUND = {
    "elevation_m": 1,
    "slope_deg": 2,
    "ndvi_mean": 3,
    "ndvi_now": 3,
    "vci": 1,
    "crude_protein_pct": 1,
    "soil_moisture": 3,
    "temperature_c": 1,
    "humidity_pct": 1,
    "evapotranspiration_mm": 2,
    "urban_fraction": 3,
}


def grid_cells(
    bbox: tuple[float, float, float, float] | None = None,
    stride: int = 1,
) -> dict:
    """Return grid cells with their stored layer values, for map rendering.

    Read-only: never touches Earth Engine. Optionally restricted to an
    ``(south, west, north, east)`` bounding box. The realized grid spec is
    returned so a client can paint the regular lattice as a raster overlay.

    ``stride`` subsamples the lattice (every Nth row and column) so a zoomed-out
    request over a large bbox stays bounded in size — at full 250 m resolution
    the whole county is ~1.5M cells, far too many to return at once. The returned
    ``stride`` lets the client paint each sampled cell as one block-pixel.
    """
    spec = _load_spec()
    schema = db_client.schema
    stride = max(1, int(stride))
    base = (
        f'''SELECT c.cell_id, c.row_idx, c.col_idx, c.latitude, c.longitude,
                   c.elevation_m, c.slope_deg, c.ndvi_mean,
                   c.urban_fraction,
                   d.ndvi_now, d.vci, d.crude_protein_pct,
                   d.soil_moisture, d.temperature_c, d.humidity_pct,
                   d.evapotranspiration_mm
            FROM "{schema}".grid_cells c
            LEFT JOIN "{schema}".grid_dynamic d ON d.cell_id = c.cell_id'''
    )
    conds: list[str] = []
    params: list = []
    if bbox is not None:
        s, w, n, e = bbox
        conds.append("c.latitude BETWEEN %s AND %s AND c.longitude BETWEEN %s AND %s")
        params.extend([s, n, w, e])
    if stride > 1:
        conds.append("c.row_idx %% %s = 0 AND c.col_idx %% %s = 0")
        params.extend([stride, stride])
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    rows = db_client.fetch_all(base + where + " ORDER BY c.cell_id", tuple(params) or None)

    cells: list[dict] = []
    for r in rows:
        cell = {
            "id": r["cell_id"],
            "row": r["row_idx"],
            "col": r["col_idx"],
            "lat": _round(float(r["latitude"]), 5),
            "lon": _round(float(r["longitude"]), 5),
        }
        for field in _CELL_LAYER_FIELDS:
            cell[field] = _round(r.get(field), _CELL_ROUND[field])
        cell["drought_status"] = nutrition.drought_status(r.get("vci"))
        cells.append(cell)

    return {
        "spec": {
            "resolution_m": round(spec.resolution_deg * 111_320.0, 1),
            "resolution_deg": spec.resolution_deg,
            "south": spec.south,
            "west": spec.west,
            "north": spec.north,
            "east": spec.east,
            "nrows": spec.nrows,
            "ncols": spec.ncols,
        },
        "stride": stride,
        "count": len(cells),
        "cells": cells,
        "freshness": _layer_freshness(),
    }


def engine_meta() -> dict:
    """Static metadata for clients: species, wards, county centroid, grid state."""
    from ..core_math.energy import SPECIES_PROFILES
    from ..geo.wards import county_centroid

    species = [
        {"key": p.key, "label": p.label, "body_mass_kg": p.body_mass_kg}
        for p in SPECIES_PROFILES.values()
    ]
    wards = [
        {"name": w.name, "latitude": w.latitude, "longitude": w.longitude}
        for w in WARDS.values()
    ]
    clat, clon = county_centroid()
    meta = db_client.fetch_one(
        f'SELECT id FROM "{db_client.schema}".grid_meta WHERE id = 1'
    )
    return {
        "species": species,
        "wards": wards,
        "centroid": {"latitude": clat, "longitude": clon},
        "grid_built": meta is not None,
    }


def _densify(path_lonlat: list[list[float]], step_km: float) -> list[tuple[float, float]]:
    """Insert intermediate points so samples are ~step_km apart. Returns lat/lon."""
    if len(path_lonlat) < 2:
        return [(p[1], p[0]) for p in path_lonlat]
    dense: list[tuple[float, float]] = [(path_lonlat[0][1], path_lonlat[0][0])]
    for (lon1, lat1), (lon2, lat2) in zip(path_lonlat, path_lonlat[1:]):
        seg_km = haversine_km(lat1, lon1, lat2, lon2)
        steps = max(1, int(math.ceil(seg_km / step_km)))
        for s in range(1, steps + 1):
            frac = s / steps
            dense.append((lat1 + (lat2 - lat1) * frac, lon1 + (lon2 - lon1) * frac))
    return dense


def _resolve_point(
    zone: str | None, lat: float | None, lon: float | None, label: str
) -> tuple[float, float]:
    if zone is not None:
        if zone not in WARDS:
            raise ValueError(f"Unknown {label} ward '{zone}'")
        w = WARDS[zone]
        return w.latitude, w.longitude
    if lat is None or lon is None:
        raise ValueError(f"Provide either a ward name or lat/lon for {label}.")
    return lat, lon


def journey(
    species: str,
    *,
    origin_zone: str | None = None,
    origin_lat: float | None = None,
    origin_lon: float | None = None,
    destination_zone: str | None = None,
    destination_lat: float | None = None,
    destination_lon: float | None = None,
    sample_step_km: float = 2.0,
) -> dict:
    """Assess a livestock journey purely from the pre-computed grid.

    Routes around public conservancies, samples the grid's stored elevation along
    the routed path for the real climb, averages forage quantity/quality across
    the corridor cells, and runs the energy+protein feed-gap model. No live GEE.
    """
    resolve_profile(species)  # validate species early
    spec = _load_spec()

    o_lat, o_lon = _resolve_point(origin_zone, origin_lat, origin_lon, "origin")
    d_lat, d_lon = _resolve_point(destination_zone, destination_lat, destination_lon, "destination")

    routing = route_around((o_lon, o_lat), (d_lon, d_lat), obstacle_source.get_obstacles())
    distance_km = routing["routed_distance_km"]

    # Sample the routed path finely enough that every grid cell the corridor
    # crosses is captured — even on a sub-kilometre journey. Sampling at half the
    # cell width (Nyquist) guarantees no traversed cell is skipped; we never
    # sample coarser than the caller's step and floor the step at ~50 m so a tiny
    # journey still resolves its terrain instead of collapsing to one point.
    resolution_m = spec.resolution_deg * 111_320.0
    step_km = max(0.05, min(sample_step_km, (resolution_m / 1000.0) * 0.5))
    samples = _densify(routing["path"], step_km)

    # Ordered sequence of distinct cells the path crosses (consecutive duplicates
    # collapsed) preserves the true climb profile; the set drives forage means.
    ordered_cells: list[int] = []
    for s_lat, s_lon in samples:
        cid, _, _ = spec.nearest_cell(s_lat, s_lon)
        if not ordered_cells or ordered_cells[-1] != cid:
            ordered_cells.append(cid)
    cell_map = _fetch_cells(set(ordered_cells))

    elevations: list[float] = []
    vci_vals: list[float] = []
    ndvi_vals: list[float] = []
    cp_vals: list[float] = []
    sm_vals: list[float] = []
    temp_vals: list[float] = []
    hum_vals: list[float] = []
    et_vals: list[float] = []
    seen: set[int] = set()
    cells_used = 0
    for cid in ordered_cells:
        cell = cell_map.get(cid)
        if cell is None:
            continue
        if cell.get("elevation_m") is not None:
            elevations.append(float(cell["elevation_m"]))
        if cid not in seen:
            seen.add(cid)
            cells_used += 1
            if cell.get("vci") is not None:
                vci_vals.append(float(cell["vci"]))
            if cell.get("ndvi_now") is not None:
                ndvi_vals.append(float(cell["ndvi_now"]))
            if cell.get("crude_protein_pct") is not None:
                cp_vals.append(float(cell["crude_protein_pct"]))
            if cell.get("soil_moisture") is not None:
                sm_vals.append(float(cell["soil_moisture"]))
            if cell.get("temperature_c") is not None:
                temp_vals.append(float(cell["temperature_c"]))
            if cell.get("humidity_pct") is not None:
                hum_vals.append(float(cell["humidity_pct"]))
            if cell.get("evapotranspiration_mm") is not None:
                et_vals.append(float(cell["evapotranspiration_mm"]))

    elevation_gain = (
        round(sum(max(0.0, elevations[i + 1] - elevations[i]) for i in range(len(elevations) - 1)), 1)
        if len(elevations) >= 2
        else 0.0
    )
    mean_vci = round(sum(vci_vals) / len(vci_vals), 1) if vci_vals else None
    mean_ndvi = round(sum(ndvi_vals) / len(ndvi_vals), 3) if ndvi_vals else None
    mean_cp = round(sum(cp_vals) / len(cp_vals), 1) if cp_vals else None
    mean_sm = round(sum(sm_vals) / len(sm_vals), 3) if sm_vals else None
    mean_temp = round(sum(temp_vals) / len(temp_vals), 1) if temp_vals else None
    mean_hum = round(sum(hum_vals) / len(hum_vals), 1) if hum_vals else None
    mean_et = round(sum(et_vals) / len(et_vals), 2) if et_vals else None

    feed = assess_feed_gap(
        distance_km,
        elevation_gain,
        species,
        vci=mean_vci,
        ndvi=mean_ndvi,
        crude_protein_pct=mean_cp,
    )

    elevation_source = "grid_srtm" if elevations else "unavailable"
    forage_source = "grid" if (vci_vals or ndvi_vals or cp_vals) else "unavailable"

    return {
        "species": feed["species"],
        "species_label": feed["species_label"],
        "origin": {"latitude": o_lat, "longitude": o_lon, "zone": origin_zone},
        "destination": {"latitude": d_lat, "longitude": d_lon, "zone": destination_zone},
        "routing": {
            "straight_line_km": routing["straight_line_km"],
            "routed_distance_km": routing["routed_distance_km"],
            "detour_factor": routing["detour_factor"],
            "obstacles_avoided": routing["obstacles_avoided"],
            "path": [[lat, lon] for lon, lat in routing["path"]],
        },
        "terrain": {
            "elevation_gain_meters": elevation_gain,
            "cells_sampled": len(elevations),
        },
        "corridor_forage": {
            "mean_vci": mean_vci,
            "mean_ndvi": mean_ndvi,
            "mean_crude_protein_pct": mean_cp,
            "drought_status": nutrition.drought_status(mean_vci),
            "cells_used": cells_used,
        },
        "corridor_conditions": {
            "mean_soil_moisture_m3_m3": mean_sm,
            "mean_temperature_c": mean_temp,
            "mean_humidity_pct": mean_hum,
            "mean_evapotranspiration_mm_per_day": mean_et,
        },
        "feed_assessment": feed,
        "data_sources": {
            "distance": "osm_obstacle_routed",
            "elevation": elevation_source,
            "forage": forage_source,
            "live_gee": False,
            "served_from": "precomputed_grid",
        },
        "freshness": _layer_freshness(),
    }
