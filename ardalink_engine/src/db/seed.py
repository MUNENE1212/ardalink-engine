"""Idempotent seeding of the engine tables with Isiolo County reference data.

The rangeland matrix is generated from ward centroids and elevation baselines so
that every directed ward pair resolves to a real movement vector. Water nodes and
livestock corridors are seeded with representative WPdx / ILRI-style records.
"""

from __future__ import annotations

import json

from ..geo.wards import WARDS, WARD_NAMES, haversine_km
from ..logging_config import get_logger
from .client import DatabaseClient

logger = get_logger("ardalink.db.seed")


def _build_rangeland_rows() -> list[tuple]:
    """Generate directed ward-to-ward vectors for all ordered ward pairs."""
    rows: list[tuple] = []
    for origin in WARD_NAMES:
        for dest in WARD_NAMES:
            if origin == dest:
                continue
            o, d = WARDS[origin], WARDS[dest]
            distance_km = round(haversine_km(o.latitude, o.longitude, d.latitude, d.longitude), 3)
            elevation_gain = round(max(0.0, d.elevation_m - o.elevation_m), 1)
            # Composite energy tax index (unitless, ~0-100) combining horizontal
            # travel and vertical climb — a quick-glance routing penalty.
            energy_tax_index = round(min(100.0, distance_km * 0.45 + elevation_gain * 0.04), 2)
            vci = round((o.vci_base + d.vci_base) / 2, 1)
            water = round((o.water_score_base + d.water_score_base) / 2, 1)
            rows.append(
                (origin, dest, distance_km, elevation_gain, energy_tax_index, vci, water)
            )
    return rows


# Representative WPdx-aligned water points across the wards.
_WATER_NODES: list[tuple] = [
    # wpdx_id, name, lat, lon, source_type, status, last_verified, queue_index
    ("WPDX-ISL-0001", "Game Community Borehole", 0.3601, 37.5905, "borehole", "functional", "2026-04-12", 3),
    ("WPDX-ISL-0002", "Wabera Town Shallow Well", 0.3475, 37.5811, "shallow well", "functional", "2026-03-28", 2),
    ("WPDX-ISL-0003", "Burat Water Pan", 0.4112, 37.5523, "water pan", "non-functional", "2026-02-15", 5),
    ("WPDX-ISL-0004", "Ngaremara Borehole", 0.5044, 37.6033, "borehole", "functional", "2026-04-30", 4),
    ("WPDX-ISL-0005", "Oldonyiro Community Borehole", 0.7488, 36.9521, "borehole", "functional", "2026-04-02", 3),
    ("WPDX-ISL-0006", "Chari Water Pan", 0.5523, 38.2044, "water pan", "dry", "2026-01-20", 5),
    ("WPDX-ISL-0007", "Cherab Strategic Borehole", 0.8533, 38.6011, "borehole", "non-functional", "2026-02-09", 5),
    ("WPDX-ISL-0008", "Garba Tulla Town Borehole", 0.5312, 38.5024, "borehole", "functional", "2026-05-04", 3),
    ("WPDX-ISL-0009", "Kinna Shallow Well", 0.1033, 38.3522, "shallow well", "functional", "2026-04-18", 2),
    ("WPDX-ISL-0010", "Sericho Water Pan", 0.7522, 38.9011, "water pan", "dry", "2026-01-11", 5),
    ("WPDX-ISL-0011", "Bulla Pesa Urban Borehole", 0.3555, 37.5862, "borehole", "functional", "2026-05-10", 2),
    ("WPDX-ISL-0012", "Sericho Emergency Borehole", 0.7601, 38.8800, "borehole", "functional", "2026-05-01", 4),
]


def _build_corridor_rows() -> list[tuple]:
    """Representative ILRI/ICPALD livestock route geometries (LineString coords)."""
    def line(*wards: str) -> str:
        coords = [[WARDS[w].longitude, WARDS[w].latitude] for w in wards]
        return json.dumps({"type": "LineString", "coordinates": coords})

    return [
        ("LC-ISL-N1", "Oldonyiro-Burat Dry Season Route",
         line("Oldonyiro", "Burat", "Bulla Pesa"), 0.62, 0.35),
        ("LC-ISL-E1", "Garba Tulla-Cherab Pastoral Corridor",
         line("Garba Tulla", "Cherab", "Sericho"), 0.78, 0.71),
        ("LC-ISL-S1", "Kinna-Garba Tulla Trekking Route",
         line("Kinna", "Garba Tulla", "Chari"), 0.55, 0.48),
        ("LC-ISL-C1", "Ngaremara-Chari Transhumance Path",
         line("Ngaremara", "Burat", "Chari"), 0.66, 0.52),
        ("LC-ISL-W1", "Wabera-Oldonyiro Wet Season Route",
         line("Wabera", "Bulla Pesa", "Oldonyiro"), 0.49, 0.29),
    ]


def seed_all(client: DatabaseClient) -> dict[str, int]:
    """Seed all tables when empty. Returns the row counts present after seeding."""
    counts: dict[str, int] = {}

    with client.connection() as conn:
        with conn.cursor() as cur:
            # Rangeland matrix
            cur.execute(f'SELECT COUNT(*) FROM "{client.schema}".isiolo_rangeland_matrix')
            if cur.fetchone()[0] == 0:
                cur.executemany(
                    f'''INSERT INTO "{client.schema}".isiolo_rangeland_matrix
                        (origin_zone, destination_zone, distance_km, elevation_gain_meters,
                         energy_tax_index, vegetation_index_vci, water_availability_score)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (origin_zone, destination_zone) DO NOTHING''',
                    _build_rangeland_rows(),
                )
                logger.info("Seeded isiolo_rangeland_matrix")

            # Water nodes
            cur.execute(f'SELECT COUNT(*) FROM "{client.schema}".water_nodes')
            if cur.fetchone()[0] == 0:
                cur.executemany(
                    f'''INSERT INTO "{client.schema}".water_nodes
                        (wpdx_id, name, latitude, longitude, water_source_type,
                         functional_status, last_verified_date, queue_time_index)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (wpdx_id) DO NOTHING''',
                    _WATER_NODES,
                )
                logger.info("Seeded water_nodes")

            # Livestock corridors
            cur.execute(f'SELECT COUNT(*) FROM "{client.schema}".livestock_corridors')
            if cur.fetchone()[0] == 0:
                cur.executemany(
                    f'''INSERT INTO "{client.schema}".livestock_corridors
                        (route_id, route_name, geometry_path, soil_friction_factor, conflict_risk_score)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (route_id) DO NOTHING''',
                    _build_corridor_rows(),
                )
                logger.info("Seeded livestock_corridors")

            for table in ("isiolo_rangeland_matrix", "water_nodes", "livestock_corridors"):
                cur.execute(f'SELECT COUNT(*) FROM "{client.schema}".{table}')
                counts[table] = cur.fetchone()[0]

    logger.info("Seed complete: %s", counts)
    return counts
