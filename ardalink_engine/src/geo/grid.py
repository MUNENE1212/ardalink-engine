"""Regular environmental grid over Isiolo County.

The engine pre-computes every environmental layer onto a regular lat/lon lattice
that covers the Isiolo bounding box, and stores the result in Postgres. Because
the lattice is *regular*, the nearest cell to any point is pure arithmetic — no
spatial index, KNN, or PostGIS extension is required. A query maps a GPS point
to a cell in O(1) and then fetches that cell by its integer primary key.

Grid geometry
-------------
* ``resolution_deg`` — cell side length in degrees, derived from the configured
  metres at the county latitude (near the equator the lon/lat scale difference is
  small, so a single degree pitch is used for both axes).
* The origin is the south-west corner of the Isiolo bounding box.
* ``cell_id = row * ncols + col`` — a stable integer key. ``row`` increases
  north, ``col`` increases east. Cell centres sit at half-step offsets.

The realised grid parameters are persisted in the ``grid_meta`` table at build
time so queries stay correct even if the configured resolution later changes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import settings

# Metres per degree of latitude (mean). Longitude is scaled by cos(latitude).
_METRES_PER_DEG_LAT = 111_320.0


@dataclass(frozen=True)
class GridSpec:
    """Realised parameters of a built grid."""

    resolution_deg: float
    south: float
    west: float
    north: float
    east: float
    nrows: int
    ncols: int

    @property
    def cell_count(self) -> int:
        return self.nrows * self.ncols

    def cell_center(self, row: int, col: int) -> tuple[float, float]:
        """Return ``(lat, lon)`` of the centre of cell ``(row, col)``."""
        lat = self.south + (row + 0.5) * self.resolution_deg
        lon = self.west + (col + 0.5) * self.resolution_deg
        return lat, lon

    def cell_bounds(self, row: int, col: int) -> tuple[float, float, float, float]:
        """Return ``(s, w, n, e)`` of cell ``(row, col)``."""
        s = self.south + row * self.resolution_deg
        w = self.west + col * self.resolution_deg
        return s, w, s + self.resolution_deg, w + self.resolution_deg

    def cell_id(self, row: int, col: int) -> int:
        return row * self.ncols + col

    def row_col(self, cell_id: int) -> tuple[int, int]:
        return divmod(cell_id, self.ncols)

    def contains(self, lat: float, lon: float) -> bool:
        return self.south <= lat <= self.north and self.west <= lon <= self.east

    def nearest_cell(self, lat: float, lon: float) -> tuple[int, int, int]:
        """Map ``(lat, lon)`` to the nearest cell. Returns ``(cell_id, row, col)``.

        Points outside the grid are clamped to the nearest edge cell (the caller
        decides whether to flag that as out-of-coverage via :meth:`contains`).
        """
        col = int((lon - self.west) / self.resolution_deg)
        row = int((lat - self.south) / self.resolution_deg)
        col = max(0, min(self.ncols - 1, col))
        row = max(0, min(self.nrows - 1, row))
        return self.cell_id(row, col), row, col


def resolution_deg(resolution_m: float | None = None) -> float:
    """Convert a cell size in metres to degrees at the county latitude."""
    metres = resolution_m if resolution_m is not None else settings.GRID_RESOLUTION_M
    return metres / _METRES_PER_DEG_LAT


def spec_from_config(resolution_m: float | None = None) -> GridSpec:
    """Build a :class:`GridSpec` from the configured bbox and resolution."""
    south, west, north, east = settings.ISIOLO_BBOX
    res = resolution_deg(resolution_m)
    ncols = int(math.ceil((east - west) / res))
    nrows = int(math.ceil((north - south) / res))
    return GridSpec(
        resolution_deg=res,
        south=south,
        west=west,
        north=north,
        east=east,
        nrows=nrows,
        ncols=ncols,
    )


def spec_from_meta(meta: dict) -> GridSpec:
    """Reconstruct a :class:`GridSpec` from a persisted ``grid_meta`` row."""
    return GridSpec(
        resolution_deg=float(meta["resolution_deg"]),
        south=float(meta["south"]),
        west=float(meta["west"]),
        north=float(meta["north"]),
        east=float(meta["east"]),
        nrows=int(meta["nrows"]),
        ncols=int(meta["ncols"]),
    )
