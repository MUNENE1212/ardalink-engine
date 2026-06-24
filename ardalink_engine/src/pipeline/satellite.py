"""Google Earth Engine ingestion of dynamic vegetation indices (VCI).

Computes a real Vegetation Condition Index per ward from the MODIS NDVI archive:

    VCI = 100 * (NDVI_now - NDVI_min) / (NDVI_max - NDVI_min)

where the min/max envelope is taken over the full MODIS record for the ward
footprint and ``NDVI_now`` is a recent composite. Two corrections from the
original design contract are applied:

* Urban mask — pixels classified as built-up by ESA WorldCover (class 50) are
  masked out so dense settlement does not distort rangeland greenness.
* Prosopis juliflora penalty — a flat multiplicative discount applied to the
  resulting VCI, since invasive pod cover inflates raw NDVI without offering
  equivalent forage value. (A dedicated Prosopis distribution layer can later
  localise this; for now it is a transparent flat correction.)

Earth Engine is accessed lazily via :mod:`src.pipeline.gee`. Per-ward results
are cached in-memory with a TTL.
"""

from __future__ import annotations

import time

from ..config import settings
from ..geo.wards import WARDS
from ..logging_config import get_logger
from .gee import ensure_initialized

logger = get_logger("ardalink.pipeline.satellite")

# 16-day 250 m MODIS NDVI.
MODIS_NDVI_PRODUCT = "MODIS/061/MOD13Q1"
MODIS_NDVI_BAND = "NDVI"
# ESA WorldCover 10 m land cover (class 50 = built-up).
WORLDCOVER_PRODUCT = "ESA/WorldCover/v200"
WORLDCOVER_BUILTUP_CLASS = 50
# Radius (m) approximating a ward footprint around its centroid for reduction.
WARD_FOOTPRINT_RADIUS_M = 8000
# Recent window (days) used for the "current" NDVI composite.
CURRENT_WINDOW_DAYS = 90
# Multiplicative correction discounting greenness contributed by invasive Prosopis.
PROSOPIS_PENALTY_FACTOR = 0.85
# Cache TTL for per-ward VCI (seconds).
VCI_CACHE_TTL_SECONDS = 21600

_CACHE: dict[str, tuple[float, dict]] = {}


def fetch_vegetation_index(ward_name: str) -> dict:
    """Fetch the corrected VCI for a single ward.

    Returns ``{vci, ndvi_now, ndvi_min, ndvi_max, urban_masked, prosopis_factor}``.
    Raises GEENotConfigured / GEEInitError when Earth Engine is unavailable.
    """
    if ward_name not in WARDS:
        raise ValueError(f"Unknown ward '{ward_name}'")

    now = time.time()
    cached = _CACHE.get(ward_name)
    if cached and (now - cached[0]) < VCI_CACHE_TTL_SECONDS:
        return cached[1]

    ensure_initialized()
    import ee  # lazy — only after successful init

    ward = WARDS[ward_name]
    region = ee.Geometry.Point([ward.longitude, ward.latitude]).buffer(WARD_FOOTPRINT_RADIUS_M)

    ndvi = ee.ImageCollection(MODIS_NDVI_PRODUCT).select(MODIS_NDVI_BAND)
    ndvi_min = ndvi.min()
    ndvi_max = ndvi.max()

    end = ee.Date(int(now * 1000))
    start = end.advance(-CURRENT_WINDOW_DAYS, "day")
    current = ndvi.filterDate(start, end).mean()

    # Urban mask: drop pixels classified as built-up by ESA WorldCover.
    worldcover = ee.ImageCollection(WORLDCOVER_PRODUCT).first().select("Map")
    urban_mask = worldcover.neq(WORLDCOVER_BUILTUP_CLASS)

    denom = ndvi_max.subtract(ndvi_min)
    vci_img = (
        current.subtract(ndvi_min)
        .divide(denom)
        .multiply(100)
        .updateMask(denom.gt(0))
        .updateMask(urban_mask)
        .rename("VCI")
    )

    stats = (
        vci_img.addBands(current.rename("now"))
        .addBands(ndvi_min.rename("nmin"))
        .addBands(ndvi_max.rename("nmax"))
        .reduceRegion(ee.Reducer.mean(), region, 250)
        .getInfo()
    )

    raw_vci = stats.get("VCI")
    if raw_vci is None:
        raise RuntimeError(f"MODIS VCI reduction returned no data for ward '{ward_name}'")

    corrected = max(0.0, min(100.0, raw_vci * PROSOPIS_PENALTY_FACTOR))
    result = {
        "vci": round(corrected, 1),
        "ndvi_now": stats.get("now"),
        "ndvi_min": stats.get("nmin"),
        "ndvi_max": stats.get("nmax"),
        "urban_masked": True,
        "prosopis_factor": PROSOPIS_PENALTY_FACTOR,
    }
    _CACHE[ward_name] = (now, result)
    logger.info("Live VCI for %s: %.1f (raw %.1f)", ward_name, corrected, raw_vci)
    return result


def ingest_all_wards() -> dict[str, dict]:
    """Fetch corrected live VCI for every ward."""
    logger.info("Satellite VCI ingestion requested for schema '%s'", settings.DB_SCHEMA)
    return {name: fetch_vegetation_index(name) for name in WARDS}
