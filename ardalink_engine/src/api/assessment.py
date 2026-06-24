"""Spatial assessment service: DB lookup + energy math + ground-truth cross-reference."""

from __future__ import annotations

from ..ai import azure_client
from ..config import settings
from ..core_math.energy import assess_energy
from ..db.client import db_client
from ..geo.routing import route_around
from ..geo.wards import WARDS, haversine_km, reported_quadrant
from ..logging_config import get_logger
from ..pipeline import obstacles as obstacle_source
from ..pipeline.satellite import fetch_vegetation_index
from ..pipeline.srtm_terrain import elevation_profile_along_path

logger = get_logger("ardalink.api.assessment")


class ZonePairNotFound(LookupError):
    """Raised when no rangeland vector exists for the requested ward pair."""


def _lookup_vector(origin_zone: str, destination_zone: str) -> dict:
    """Fast index lookup of the directed ward-to-ward movement vector."""
    row = db_client.fetch_one(
        f'''SELECT distance_km, elevation_gain_meters, energy_tax_index,
                   vegetation_index_vci, water_availability_score
            FROM "{db_client.schema}".isiolo_rangeland_matrix
            WHERE origin_zone = %s AND destination_zone = %s''',
        (origin_zone, destination_zone),
    )
    if row is None:
        raise ZonePairNotFound(
            f"No rangeland vector for {origin_zone} -> {destination_zone}"
        )
    return row


def _nearest_functional_water_km(destination_zone: str) -> float | None:
    """Trekking distance from the destination ward to the nearest functional node.

    Returns ``None`` when no functional water node exists (avoids non-JSON ``inf``).
    """
    dest = WARDS[destination_zone]
    nodes = db_client.fetch_all(
        f'''SELECT latitude, longitude FROM "{db_client.schema}".water_nodes
            WHERE functional_status = %s''',
        ("functional",),
    )
    if not nodes:
        return None
    return round(
        min(
            haversine_km(dest.latitude, dest.longitude, n["latitude"], n["longitude"])
            for n in nodes
        ),
        2,
    )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _ground_truth(
    destination_zone: str,
    vector: dict,
    energy: dict,
    feed_grams: float,
) -> dict:
    """Derive the 7 key ground-truth indicators from the available GIS data."""
    vci = float(vector["vegetation_index_vci"])
    water = float(vector["water_availability_score"])
    stress = float(energy["physiological_stress"])

    # Combined forage/water adequacy on a 0-1 scale.
    forage_score = 0.6 * (vci / 100.0) + 0.4 * (water / 100.0)

    bcs = _clamp(1.5 + 3.5 * forage_score - 1.0 * stress, 1.0, 5.0)
    offtake = 8.0 + 12.0 * (1.0 - forage_score)
    mortality = 2.0 + 10.0 * (1.0 - forage_score) + 3.0 * stress

    profile_milk = float(energy.get("_base_milk_l_per_day", 0.0))
    milk = max(0.0, profile_milk * forage_score * (1.0 - 0.5 * stress))

    dest = WARDS[destination_zone]
    return {
        "body_condition_score": round(bcs, 1),
        "offtake_rate_percent": round(offtake, 1),
        "mortality_rate_percent": round(mortality, 1),
        "milk_production_l_per_day": round(milk, 2),
        "water_trekking_distance_km": _nearest_functional_water_km(destination_zone),
        "supplementary_feeding_kg_per_day": round(feed_grams / 1000.0, 3),
        "reported_quadrant": reported_quadrant(dest.latitude, dest.longitude),
    }


def run_assessment(
    origin_zone: str,
    destination_zone: str,
    species: str,
    include_ai_summary: bool = True,
) -> dict:
    """Run the full spatial-biophysical assessment for a ward pair and species."""
    vector = dict(_lookup_vector(origin_zone, destination_zone))
    elevation_gain = float(vector["elevation_gain_meters"])

    # Live obstacle-aware routing: detour around public conservancies / protected
    # areas so distance (and therefore energy/feed) reflects the real walked path.
    origin = WARDS[origin_zone]
    destination = WARDS[destination_zone]
    routing = route_around(
        (origin.longitude, origin.latitude),
        (destination.longitude, destination.latitude),
        obstacle_source.get_obstacles(),
    )
    distance_km = routing["routed_distance_km"]

    # Live Earth Engine enrichment: real SRTM climb along the routed path and
    # live MODIS-derived VCI for the destination ward. Falls back to the baseline
    # seed values with an explicit status when GEE is unconfigured or errors.
    gee_status = "gee_not_configured"
    elevation_source = "baseline_seed"
    vegetation_source = "baseline_seed"
    terrain = None
    if settings.gee_configured:
        gee_status = "live"
        try:
            terrain = elevation_profile_along_path(routing["path"])
            elevation_gain = terrain["elevation_gain_meters"]
            elevation_source = "srtm_live"
        except Exception as exc:  # broad: any GEE/network failure → graceful fallback
            gee_status = "gee_error"
            logger.warning("Live SRTM elevation failed, using baseline: %s", exc)
        try:
            veg = fetch_vegetation_index(destination_zone)
            vector["vegetation_index_vci"] = veg["vci"]
            vegetation_source = "modis_live"
        except Exception as exc:  # broad: any GEE/network failure → graceful fallback
            gee_status = "gee_error"
            logger.warning("Live MODIS VCI failed, using baseline: %s", exc)

    energy = assess_energy(distance_km, elevation_gain, species)

    # Attach the species base milk yield for the milk indicator derivation.
    from ..core_math.energy import resolve_profile
    energy["_base_milk_l_per_day"] = resolve_profile(species).base_milk_l_per_day

    feed_grams = energy["feed_recommendation_grams"]
    ground_truth = _ground_truth(destination_zone, vector, energy, feed_grams)

    ai_status = "skipped"
    ai_summary = None
    if include_ai_summary:
        context = {
            "origin_zone": origin_zone,
            "destination_zone": destination_zone,
            "species": energy["species_label"],
            "distance_km": distance_km,
            "elevation_penalty_meters": elevation_gain,
            "energy_tax_mj": energy["energy"]["total_mj"],
            "feed_recommendation_grams": feed_grams,
            "ground_truth": ground_truth,
        }
        if not azure_client.is_configured():
            ai_status = "azure_not_configured"
            logger.info("AI summary requested but Azure OpenAI is not configured")
        else:
            try:
                ai_summary = azure_client.environmental_summary(context)
                ai_status = "ok"
            except azure_client.AzureOpenAIError as exc:
                ai_status = "azure_error"
                logger.warning("Azure summary failed: %s", exc)

    return {
        "origin_zone": origin_zone,
        "destination_zone": destination_zone,
        "species": energy["species"],
        "species_label": energy["species_label"],
        "distance_km": round(distance_km, 3),
        "elevation_penalty_meters": round(elevation_gain, 1),
        "energy_index": float(vector["energy_tax_index"]),
        "energy_tax_mj": energy["energy"],
        "physiological_stress": energy["physiological_stress"],
        "feed_recommendation_grams": feed_grams,
        "ground_truth": ground_truth,
        "routing": {
            "straight_line_km": routing["straight_line_km"],
            "routed_distance_km": routing["routed_distance_km"],
            "detour_factor": routing["detour_factor"],
            "obstacles_avoided": routing["obstacles_avoided"],
        },
        "terrain": terrain,
        "data_sources": {
            "distance": "osm_obstacle_routed",
            "elevation": elevation_source,
            "vegetation": vegetation_source,
            "gee_status": gee_status,
        },
        "ai_status": ai_status,
        "ai_summary": ai_summary,
    }
