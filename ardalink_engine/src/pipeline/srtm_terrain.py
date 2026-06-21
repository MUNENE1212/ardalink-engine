"""NASA/SRTM digital-elevation sampling for real climb energy.

Given the (obstacle-aware) route between two wards, this module samples the
SRTM 30 m DEM at points densified along the path and computes the cumulative
*positive* elevation gain — the climb the animal actually pays energy for.

Earth Engine is required and accessed lazily via :mod:`src.pipeline.gee`.
Results are cached in-memory per route key to keep repeat requests fast.
"""

from __future__ import annotations

import math

from ..geo.wards import haversine_km
from ..logging_config import get_logger
from .gee import ensure_initialized

logger = get_logger("ardalink.pipeline.srtm_terrain")

# SRTM 30 m global DEM (band: 'elevation'). Near-equator coverage is complete.
SRTM_PRODUCT = "USGS/SRTMGL1_003"
# Spacing between elevation samples along the route.
SAMPLE_STEP_KM = 2.0
# Cap on number of sampled points (keeps the single getInfo call light).
MAX_SAMPLES = 160

_CACHE: dict[str, dict] = {}


def _densify(path_lonlat: list[list[float]], step_km: float) -> list[list[float]]:
    """Insert intermediate points so consecutive samples are ~step_km apart."""
    if len(path_lonlat) < 2:
        return list(path_lonlat)
    dense: list[list[float]] = [list(path_lonlat[0])]
    for (lon1, lat1), (lon2, lat2) in zip(path_lonlat, path_lonlat[1:]):
        seg_km = haversine_km(lat1, lon1, lat2, lon2)
        steps = max(1, int(math.ceil(seg_km / step_km)))
        for s in range(1, steps + 1):
            frac = s / steps
            dense.append([lon1 + (lon2 - lon1) * frac, lat1 + (lat2 - lat1) * frac])
    return dense


def _route_key(path_lonlat: list[list[float]]) -> str:
    return ";".join(f"{lon:.4f},{lat:.4f}" for lon, lat in path_lonlat)


def elevation_profile_along_path(path_lonlat: list[list[float]]) -> dict:
    """Sample SRTM along the route and return cumulative climb statistics.

    Returns ``{elevation_gain_meters, min_m, max_m, samples}``.
    Raises GEENotConfigured / GEEInitError (from :mod:`gee`) when unavailable.
    """
    key = _route_key(path_lonlat)
    if key in _CACHE:
        return _CACHE[key]

    ensure_initialized()
    import ee  # lazy — only after successful init

    points = _densify(path_lonlat, SAMPLE_STEP_KM)
    if len(points) > MAX_SAMPLES:
        stride = int(math.ceil(len(points) / MAX_SAMPLES))
        points = points[::stride] + [points[-1]]

    dem = ee.Image(SRTM_PRODUCT).select("elevation")
    coords = ee.List([[float(lon), float(lat)] for lon, lat in points])

    def _sample(coord):
        coord = ee.List(coord)
        point = ee.Geometry.Point([coord.get(0), coord.get(1)])
        value = dem.reduceRegion(ee.Reducer.first(), point, 30).get("elevation")
        return ee.Algorithms.If(value, value, -9999)

    elevations = coords.map(_sample).getInfo()
    elevations = [e for e in elevations if e is not None and e != -9999]
    if len(elevations) < 2:
        raise RuntimeError("SRTM returned insufficient elevation samples for the route")

    gain = sum(max(0.0, elevations[i + 1] - elevations[i]) for i in range(len(elevations) - 1))
    result = {
        "elevation_gain_meters": round(gain, 1),
        "min_m": round(min(elevations), 1),
        "max_m": round(max(elevations), 1),
        "samples": len(elevations),
    }
    _CACHE[key] = result
    logger.info("SRTM profile: gain=%.1fm over %d samples", gain, len(elevations))
    return result
