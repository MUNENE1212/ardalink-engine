"""Pydantic request/response models for the spatial-assessment endpoint."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from ..core_math.energy import SPECIES_PROFILES
from ..geo.wards import WARD_NAMES

# Build enums from the single sources of truth so the contract never drifts.
ZoneEnum = Enum("ZoneEnum", {name: name for name in WARD_NAMES}, type=str)
SpeciesEnum = Enum("SpeciesEnum", {key: key for key in SPECIES_PROFILES}, type=str)


class SpatialAssessmentRequest(BaseModel):
    origin_zone: ZoneEnum = Field(..., description="Origin ward within Isiolo County")
    destination_zone: ZoneEnum = Field(..., description="Destination ward within Isiolo County")
    species: SpeciesEnum = Field(..., description="Livestock species / category")
    include_ai_summary: bool = Field(
        True, description="Whether to attach an Azure GPT-4o environmental briefing"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "origin_zone": "Oldonyiro",
                "destination_zone": "Garba Tulla",
                "species": "finishing_buck",
                "include_ai_summary": False,
            }
        }
    }


class ScheduleRunRequest(BaseModel):
    """Optional body for manually triggering a scheduled-ingestion cycle."""

    force: bool = Field(
        False,
        description="Ingest the selected layers regardless of freshness (skip the due-check).",
    )
    layers: list[str] | None = Field(
        None,
        description="Restrict the run to a subset of layers "
        "(static, vegetation, protein, climate, soil). Omit to run all due layers.",
    )

    model_config = {
        "json_schema_extra": {"example": {"force": True, "layers": ["climate", "soil"]}}
    }


class PointConditionsRequest(BaseModel):
    """A GPS point to resolve to its nearest pre-computed grid cell."""

    latitude: float = Field(..., ge=-90, le=90, description="WGS84 latitude")
    longitude: float = Field(..., ge=-180, le=180, description="WGS84 longitude")

    model_config = {
        "json_schema_extra": {"example": {"latitude": 0.354, "longitude": 37.588}}
    }


class JourneyRequest(BaseModel):
    """A livestock journey, scored entirely from the pre-computed grid.

    Provide either ward names or explicit coordinates for each endpoint.
    """

    species: SpeciesEnum = Field(..., description="Livestock species / category")
    origin_zone: ZoneEnum | None = Field(None, description="Origin ward (alternative to lat/lon)")
    origin_lat: float | None = Field(None, ge=-90, le=90)
    origin_lon: float | None = Field(None, ge=-180, le=180)
    destination_zone: ZoneEnum | None = Field(None, description="Destination ward (alternative to lat/lon)")
    destination_lat: float | None = Field(None, ge=-90, le=90)
    destination_lon: float | None = Field(None, ge=-180, le=180)

    model_config = {
        "json_schema_extra": {
            "example": {
                "species": "finishing_buck",
                "origin_zone": "Oldonyiro",
                "destination_zone": "Garba Tulla",
            }
        }
    }


class BuildGridRequest(BaseModel):
    """Optional override of the configured grid resolution for a build."""

    resolution_m: float | None = Field(
        None, gt=0, description="Cell size in metres (defaults to GRID_RESOLUTION_M)"
    )
    reset: bool = Field(False, description="Truncate the existing grid before building")


class EnergyBreakdown(BaseModel):
    horizontal_mj: float
    vertical_mj: float
    total_mj: float


class GroundTruthIndicators(BaseModel):
    """The 7 key ground-truth indicators cross-referenced for the destination."""

    body_condition_score: float = Field(..., description="BCS, 1.0 (emaciated) - 5.0 (obese)")
    offtake_rate_percent: float = Field(..., description="Estimated herd offtake rate (%)")
    mortality_rate_percent: float = Field(..., description="Estimated mortality rate (%)")
    milk_production_l_per_day: float = Field(..., description="Estimated milk yield per lactating female (L/day)")
    water_trekking_distance_km: float | None = Field(
        ..., description="Distance to nearest functional water node (km); null if none functional"
    )
    supplementary_feeding_kg_per_day: float = Field(..., description="Recommended supplementary feed (kg/head/day)")
    reported_quadrant: str = Field(..., description="Reporting quadrant of the destination (NE/NW/SE/SW)")


class RoutingInfo(BaseModel):
    """Obstacle-aware routing: detour around public conservancies/protected areas."""

    straight_line_km: float = Field(..., description="Great-circle distance ignoring obstacles (km)")
    routed_distance_km: float = Field(..., description="Shortest walked distance avoiding protected areas (km)")
    detour_factor: float = Field(..., description="routed / straight-line ratio (1.0 = no detour)")
    obstacles_avoided: list[str] = Field(
        default_factory=list, description="Names of protected areas routed around"
    )


class TerrainProfile(BaseModel):
    """Live SRTM elevation profile sampled along the routed path."""

    elevation_gain_meters: float = Field(..., description="Cumulative positive climb along the route (m)")
    min_m: float = Field(..., description="Lowest sampled elevation (m)")
    max_m: float = Field(..., description="Highest sampled elevation (m)")
    samples: int = Field(..., description="Number of valid SRTM samples along the route")


class DataSources(BaseModel):
    """Provenance of each major figure so consumers know live vs baseline data."""

    distance: str = Field(..., description="How distance was derived (e.g. osm_obstacle_routed)")
    elevation: str = Field(..., description="srtm_live or baseline_seed")
    vegetation: str = Field(..., description="modis_live or baseline_seed")
    gee_status: str = Field(..., description="live, gee_not_configured, or gee_error")


class SpatialAssessmentResponse(BaseModel):
    origin_zone: str
    destination_zone: str
    species: str
    species_label: str
    distance_km: float = Field(..., description="Walked distance used for energy/feed (routed, km)")
    elevation_penalty_meters: float
    energy_index: float = Field(..., description="Composite routing energy tax index (~0-100)")
    energy_tax_mj: EnergyBreakdown
    physiological_stress: float = Field(..., description="Normalised locomotion stress (0-1)")
    feed_recommendation_grams: float = Field(..., description="Target feed block mass (grams)")
    ground_truth: GroundTruthIndicators
    routing: RoutingInfo
    terrain: TerrainProfile | None = Field(
        None, description="Live SRTM elevation profile (null unless GEE is configured)"
    )
    data_sources: DataSources
    ai_status: str = Field(..., description="Status of the Azure AI synthesis step")
    ai_summary: str | None = Field(None, description="Azure GPT-4o environmental briefing, if available")
