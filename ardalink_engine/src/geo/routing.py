"""Obstacle-aware shortest-path routing between ward centroids.

Straight-line (great-circle) distance underestimates real pastoral journeys
because herds must detour around conservancies and protected areas. This module
builds a visibility graph from the obstacle polygons plus the origin/destination,
then finds the shortest path that does not pass through any obstacle interior —
giving a realistic walked distance.

Performance: obstacles near the corridor are buffered and merged into a single
geometry (``unary_union``) and simplified, so adjacent conservancies collapse
into a handful of blobs instead of thousands of vertices. A spatial index
(``STRtree``) keeps edge/obstacle intersection tests fast.

Geometry uses lon/lat for intersection tests (adequate at county scale) while
edge weights use the haversine distance for accuracy.
"""

from __future__ import annotations

import networkx as nx
from shapely import STRtree
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from ..logging_config import get_logger
from .wards import haversine_km

logger = get_logger("ardalink.geo.routing")

# Buffer applied to obstacles (~1.3 km) so routed paths clear boundaries.
BLOCK_BUFFER_DEG = 0.012
# Extra offset (~0.4 km) placing graph nodes just outside the blocking region so
# boundary-following edges are not mistaken for crossings.
NODE_OFFSET_DEG = 0.004
# Half-width of the corridor (~33 km) within which obstacles are considered.
CORRIDOR_BUFFER_DEG = 0.3
# Polygon simplification tolerance (~0.5 km) to cap node counts.
SIMPLIFY_DEG = 0.004
# Minimum intersection length (deg) for a segment to count as crossing an area.
BLOCK_TOL = 1e-7

# In-memory cache of computed routes, keyed by rounded origin/destination coords.
# Routes are deterministic per ward pair, so this makes repeat requests instant.
_ROUTE_CACHE: dict[tuple, dict] = {}


def _polys_of(geom) -> list:
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        return [g for g in geom.geoms if g.geom_type == "Polygon" and not g.is_empty]
    return []


def _path_length_km(coords: list[tuple]) -> float:
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
        total += haversine_km(lat1, lon1, lat2, lon2)
    return total


def _straight_result(origin: tuple, dest: tuple, straight_km: float) -> dict:
    return {
        "straight_line_km": round(straight_km, 3),
        "routed_distance_km": round(straight_km, 3),
        "detour_factor": 1.0,
        "obstacles_avoided": [],
        "path": [list(origin), list(dest)],
    }


def route_around(origin_lonlat: tuple, dest_lonlat: tuple, obstacles: list[dict]) -> dict:
    """Compute the shortest obstacle-avoiding route between two lon/lat points.

    ``obstacles`` is a list of ``{"name", "geometry": shapely Polygon}``.
    Returns straight vs routed distance, the detour factor, the names of areas
    avoided, and the path as a list of ``[lon, lat]`` vertices. Results are cached
    per origin/destination so repeat assessments of the same pair are instant.
    """
    origin = tuple(origin_lonlat)
    dest = tuple(dest_lonlat)
    cache_key = (round(origin[0], 5), round(origin[1], 5), round(dest[0], 5), round(dest[1], 5))
    cached = _ROUTE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    result = _compute_route(origin, dest, obstacles)
    _ROUTE_CACHE[cache_key] = result
    return result


def _compute_route(origin: tuple, dest: tuple, obstacles: list[dict]) -> dict:
    straight_km = haversine_km(origin[1], origin[0], dest[1], dest[0])
    origin_pt, dest_pt = Point(origin), Point(dest)

    corridor = LineString([origin, dest]).buffer(CORRIDOR_BUFFER_DEG)
    direct = LineString([origin, dest])

    # Keep obstacles that sit on the corridor, that the route does not start/end
    # inside, and that the direct line actually crosses (after buffering).
    near = []
    for ob in obstacles:
        geom = ob.get("geometry")
        if geom is None or geom.is_empty or not geom.is_valid:
            continue
        if not geom.intersects(corridor):
            continue
        buffered = geom.buffer(BLOCK_BUFFER_DEG)
        if buffered.contains(origin_pt) or buffered.contains(dest_pt):
            continue
        near.append((ob, buffered))

    crossing = [(ob, buf) for ob, buf in near if direct.intersects(buf)]
    if not crossing:
        return _straight_result(origin, dest, straight_km)

    block_union = unary_union([buf for _, buf in crossing]).simplify(
        SIMPLIFY_DEG, preserve_topology=True
    )
    block_polys = _polys_of(block_union)
    if not block_polys:
        return _straight_result(origin, dest, straight_km)
    tree = STRtree(block_polys)

    def _blocked(a: tuple, b: tuple) -> bool:
        line = LineString([a, b])
        for idx in tree.query(line, predicate="intersects"):
            inter = line.intersection(block_polys[idx])
            if (not inter.is_empty) and inter.length > BLOCK_TOL:
                return True
        return False

    # Nodes sit on a ring just outside the blocking region.
    node_ring = block_union.buffer(NODE_OFFSET_DEG).simplify(
        SIMPLIFY_DEG, preserve_topology=True
    )
    nodes: list[tuple] = [origin, dest]
    for poly in _polys_of(node_ring):
        nodes.extend((round(x, 6), round(y, 6)) for x, y in poly.exterior.coords[:-1])
    nodes = list(dict.fromkeys(nodes))

    graph = nx.Graph()
    graph.add_nodes_from(nodes)
    for i in range(len(nodes)):
        a = nodes[i]
        for j in range(i + 1, len(nodes)):
            b = nodes[j]
            if not _blocked(a, b):
                graph.add_edge(a, b, weight=haversine_km(a[1], a[0], b[1], b[0]))

    try:
        path = nx.shortest_path(graph, origin, dest, weight="weight")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        logger.warning("No obstacle-free path found; returning straight-line distance")
        return _straight_result(origin, dest, straight_km)

    routed_km = _path_length_km(path)
    avoided = sorted({(ob.get("name") or "Unnamed protected area") for ob, _ in crossing})
    return {
        "straight_line_km": round(straight_km, 3),
        "routed_distance_km": round(routed_km, 3),
        "detour_factor": round(routed_km / straight_km, 3) if straight_km > 0 else 1.0,
        "obstacles_avoided": avoided,
        "path": [list(p) for p in path],
    }
