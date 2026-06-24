"""Publicly mapped movement obstacles (conservancies / protected areas).

Pastoral herds cannot walk straight through gazetted conservancies, national
reserves, and other protected areas. This module pulls those boundaries live
from OpenStreetMap via the Overpass API for the Isiolo bounding box, so the
routing engine can compute realistic detours around them.

It does **not** include private fences/ranches — that data is not publicly
mapped. When authoritative boundary files are supplied they can be merged here.

Results are cached in-memory with a TTL to avoid hammering Overpass.
"""

from __future__ import annotations

import time

import requests
from shapely.geometry import Polygon

from ..config import settings
from ..logging_config import get_logger

logger = get_logger("ardalink.pipeline.obstacles")

_CACHE: dict[str, object] = {"ts": 0.0, "data": None}


def _build_query() -> str:
    s, w, n, e = settings.ISIOLO_BBOX
    return f"""
[out:json][timeout:{int(settings.OVERPASS_TIMEOUT_SECONDS)}];
(
  way["boundary"="protected_area"]({s},{w},{n},{e});
  relation["boundary"="protected_area"]({s},{w},{n},{e});
  way["boundary"="national_park"]({s},{w},{n},{e});
  relation["boundary"="national_park"]({s},{w},{n},{e});
  way["leisure"="nature_reserve"]({s},{w},{n},{e});
  relation["leisure"="nature_reserve"]({s},{w},{n},{e});
);
out geom;
"""


def _poly_from_geom(geom: list[dict]) -> Polygon | None:
    """Build a valid shapely Polygon (lon, lat) from an Overpass geometry list."""
    coords = [(p["lon"], p["lat"]) for p in geom if "lon" in p and "lat" in p]
    if len(coords) < 4:
        return None
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    try:
        poly = Polygon(coords)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.area == 0.0:
            return None
        return poly
    except Exception:  # pragma: no cover - defensive geometry guard
        return None


def _parse(elements: list[dict]) -> list[dict]:
    obstacles: list[dict] = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        designation = (
            tags.get("protection_title")
            or tags.get("boundary")
            or tags.get("leisure")
            or "protected_area"
        )
        el_type = el.get("type")
        if el_type == "way" and "geometry" in el:
            poly = _poly_from_geom(el["geometry"])
            if poly is not None:
                obstacles.append({"name": name, "designation": designation, "geometry": poly})
        elif el_type == "relation" and "members" in el:
            for member in el["members"]:
                if (
                    member.get("type") == "way"
                    and "geometry" in member
                    and member.get("role") in ("outer", "")
                ):
                    poly = _poly_from_geom(member["geometry"])
                    if poly is not None:
                        obstacles.append(
                            {"name": name, "designation": designation, "geometry": poly}
                        )
    return obstacles


def fetch_obstacles(force: bool = False) -> list[dict]:
    """Fetch protected-area polygons, using the in-memory cache when fresh.

    Each obstacle is ``{"name", "designation", "geometry": shapely Polygon}``.
    Raises on network/HTTP errors (callers may choose to degrade gracefully).
    """
    now = time.time()
    cached = _CACHE["data"]
    if (
        not force
        and cached is not None
        and (now - float(_CACHE["ts"])) < settings.OBSTACLE_CACHE_TTL_SECONDS
    ):
        return cached  # type: ignore[return-value]

    query = _build_query()
    resp = requests.post(
        settings.OVERPASS_URL,
        data={"data": query},
        headers={
            "User-Agent": "ArdaLink-Biophysical-Engine/1.0 (Isiolo livestock routing)",
            "Accept": "application/json",
        },
        timeout=settings.OVERPASS_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    elements = resp.json().get("elements", [])
    obstacles = _parse(elements)
    _CACHE["data"] = obstacles
    _CACHE["ts"] = now
    logger.info("Fetched %d protected-area obstacle polygons from Overpass", len(obstacles))
    return obstacles


def get_obstacles() -> list[dict]:
    """Best-effort obstacle list: returns cached/empty on failure (never raises)."""
    try:
        return fetch_obstacles()
    except Exception as exc:  # network, timeout, JSON, etc.
        logger.warning("Overpass obstacle fetch failed (%s); using cache if available", exc)
        return _CACHE["data"] or []  # type: ignore[return-value]
