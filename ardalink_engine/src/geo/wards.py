"""Static geographic reference data for the 10 administrative wards of Isiolo County.

Centroid coordinates and base elevations are approximate ward references used to
derive the rangeland matrix and to anchor spatial calculations (quadrant,
nearest-water-node trekking distance). Environmental baselines (VCI and water
availability) reflect the broad west-to-east aridity gradient of the county.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Ward:
    name: str
    latitude: float
    longitude: float
    elevation_m: float
    vci_base: float          # Vegetation Condition Index baseline, 0-100
    water_score_base: float  # Water availability baseline, 0-100


# Ordered list of the 10 wards of Isiolo County.
WARDS: dict[str, Ward] = {
    "Bulla Pesa": Ward("Bulla Pesa", 0.3540, 37.5880, 1100.0, 58.0, 62.0),
    "Wabera": Ward("Wabera", 0.3490, 37.5820, 1120.0, 56.0, 64.0),
    "Burat": Ward("Burat", 0.4000, 37.5500, 1150.0, 61.0, 58.0),
    "Ngaremara": Ward("Ngaremara", 0.5000, 37.6000, 950.0, 49.0, 52.0),
    "Oldonyiro": Ward("Oldonyiro", 0.7500, 36.9500, 1300.0, 64.0, 47.0),
    "Chari": Ward("Chari", 0.5500, 38.2000, 700.0, 38.0, 40.0),
    "Cherab": Ward("Cherab", 0.8500, 38.6000, 500.0, 31.0, 33.0),
    "Garba Tulla": Ward("Garba Tulla", 0.5300, 38.5000, 600.0, 35.0, 38.0),
    "Kinna": Ward("Kinna", 0.1000, 38.3500, 700.0, 44.0, 50.0),
    "Sericho": Ward("Sericho", 0.7500, 38.9000, 450.0, 28.0, 30.0),
}

WARD_NAMES: list[str] = list(WARDS.keys())

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two coordinates in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def county_centroid() -> tuple[float, float]:
    """Mean centroid of all ward centroids."""
    lat = sum(w.latitude for w in WARDS.values()) / len(WARDS)
    lon = sum(w.longitude for w in WARDS.values()) / len(WARDS)
    return lat, lon


def reported_quadrant(lat: float, lon: float) -> str:
    """Return the reporting quadrant (NE/NW/SE/SW) relative to the county centroid."""
    c_lat, c_lon = county_centroid()
    ns = "N" if lat >= c_lat else "S"
    ew = "E" if lon >= c_lon else "W"
    return f"{ns}{ew}"
