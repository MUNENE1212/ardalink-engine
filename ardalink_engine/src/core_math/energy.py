"""Livestock locomotion energetics for Isiolo County rangelands.

The model estimates the *metabolic energy tax* an animal pays to travel between
two wards, then translates that energy deficit into the mass of supplementary
feed blocks (in grams) required to keep the animal in energy balance.

Energy model
------------
Two components make up the locomotion cost:

* Horizontal travel — a near-constant net cost of transport per unit body mass
  per metre of ground covered (``COST_HORIZONTAL_J_PER_KG_PER_M``).
* Vertical climb — the work done against gravity to raise the body mass over the
  elevation gain, scaled by muscular efficiency
  (``E_vertical = m * g * h / MUSCLE_EFFICIENCY``).

Feed model
----------
The locomotion energy is offset by metabolizable energy (ME) from feed blocks.
The required dry-matter mass accounts for the efficiency with which ME is used
for activity (``k_activity``) and the animal-category demand factor.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import nutrition

# --- Physical constants -----------------------------------------------------
GRAVITY_M_S2 = 9.81
# Net cost of horizontal terrestrial locomotion for ruminants (J per kg per m).
COST_HORIZONTAL_J_PER_KG_PER_M = 2.0
# Fraction of metabolic energy converted to mechanical work when climbing.
MUSCLE_EFFICIENCY = 0.30
# Reference locomotion energy (MJ) used to normalise physiological stress (0-1).
REFERENCE_ENERGY_MJ = 3.0

# --- Nutritional requirement constants -------------------------------------
# Maintenance metabolisable-energy requirement scales with metabolic body size
# (BW^0.75). ~0.45 MJ per kg^0.75 per day is a standard ruminant maintenance
# coefficient. (Reference: agricultural feeding-standard maintenance forms.)
ME_MAINTENANCE_MJ_PER_KG075 = 0.45
# Maintenance crude-protein requirement, also on metabolic body size (g/kg^0.75).
CP_MAINTENANCE_G_PER_KG075 = 2.8
# Daily voluntary dry-matter intake as a fraction of body weight (ruminants).
INTAKE_FRACTION_OF_BW = 0.025
# Crude-protein concentration of the supplementary feed block (% of DM).
FEED_BLOCK_CP_PCT = 18.0


@dataclass(frozen=True)
class SpeciesProfile:
    """Physiological parameters for a livestock species/category."""

    key: str
    label: str
    body_mass_kg: float
    feed_block_me_mj_per_kg: float   # Metabolizable energy density of the feed block
    activity_efficiency: float       # k — efficiency of ME use for activity (0-1)
    demand_factor: float             # Category demand multiplier (growth/finishing)
    base_milk_l_per_day: float       # Reference lactation yield for milk indicator


# Categories emphasise the goat value chain (kids vs finishing bucks) alongside
# the other dominant pastoral species of Isiolo County.
SPECIES_PROFILES: dict[str, SpeciesProfile] = {
    "young_kid": SpeciesProfile("young_kid", "Young goat kid", 12.0, 10.5, 0.62, 1.20, 0.4),
    "finishing_buck": SpeciesProfile("finishing_buck", "Finishing buck", 45.0, 11.0, 0.65, 1.05, 0.0),
    "doe": SpeciesProfile("doe", "Breeding doe", 35.0, 10.8, 0.64, 1.10, 1.2),
    "ewe": SpeciesProfile("ewe", "Breeding ewe", 38.0, 10.6, 0.64, 1.08, 0.9),
    "lamb": SpeciesProfile("lamb", "Lamb", 15.0, 10.4, 0.62, 1.18, 0.0),
    "cattle": SpeciesProfile("cattle", "Zebu cattle", 250.0, 9.8, 0.60, 1.00, 3.0),
    "camel": SpeciesProfile("camel", "Dromedary camel", 450.0, 9.5, 0.58, 0.95, 5.0),
}


def resolve_profile(species: str) -> SpeciesProfile:
    """Return the profile for a species key, raising for unknown species."""
    profile = SPECIES_PROFILES.get(species)
    if profile is None:
        raise ValueError(
            f"Unknown species '{species}'. Known: {', '.join(SPECIES_PROFILES)}"
        )
    return profile


def metabolic_energy_tax(
    distance_km: float, elevation_gain_m: float, body_mass_kg: float
) -> dict[str, float]:
    """Compute the locomotion energy cost of a journey.

    Returns horizontal, vertical and total energy in megajoules (MJ).
    """
    distance_m = distance_km * 1000.0
    horizontal_j = COST_HORIZONTAL_J_PER_KG_PER_M * body_mass_kg * distance_m
    vertical_j = (body_mass_kg * GRAVITY_M_S2 * max(0.0, elevation_gain_m)) / MUSCLE_EFFICIENCY
    total_j = horizontal_j + vertical_j
    return {
        "horizontal_mj": round(horizontal_j / 1_000_000.0, 4),
        "vertical_mj": round(vertical_j / 1_000_000.0, 4),
        "total_mj": round(total_j / 1_000_000.0, 4),
    }


def feed_blocks_grams(energy_mj: float, profile: SpeciesProfile) -> float:
    """Translate a locomotion energy deficit (MJ) into grams of feed block.

    grams = (energy / k_activity) / ME_density * 1000 * demand_factor
    """
    me_required_mj = energy_mj / profile.activity_efficiency
    kg_feed = me_required_mj / profile.feed_block_me_mj_per_kg
    grams = kg_feed * 1000.0 * profile.demand_factor
    return round(grams, 1)


def assess_energy(distance_km: float, elevation_gain_m: float, species: str) -> dict:
    """Full energy assessment for a journey by a given species/category."""
    profile = resolve_profile(species)
    energy = metabolic_energy_tax(distance_km, elevation_gain_m, profile.body_mass_kg)
    grams = feed_blocks_grams(energy["total_mj"], profile)
    stress = min(energy["total_mj"] / REFERENCE_ENERGY_MJ, 1.0)
    return {
        "species": profile.key,
        "species_label": profile.label,
        "body_mass_kg": profile.body_mass_kg,
        "energy": energy,
        "feed_recommendation_grams": grams,
        "physiological_stress": round(stress, 3),
    }


def assess_feed_gap(
    distance_km: float,
    elevation_gain_m: float,
    species: str,
    *,
    vci: float | None = None,
    ndvi: float | None = None,
    crude_protein_pct: float | None = None,
) -> dict:
    """Daily supplementary-feed requirement from an energy *and* protein balance.

    This is the nutrition-aware feed model. It compares what the animal needs in
    a day (maintenance + the locomotion tax of the trek) against what the range
    can actually supply (forage quantity from biomass/VCI, quality from crude
    protein), in both energy (MJ) and protein (g) terms, and recommends the feed
    mass that closes whichever constraint binds.

    All forage figures are modeled proxies (see :mod:`nutrition`); the returned
    ``forage`` block carries the intermediate values so the result is auditable.
    Locomotion energetics remain the source of truth and are reused unchanged.
    """
    profile = resolve_profile(species)
    bw075 = profile.body_mass_kg ** 0.75

    # --- Daily requirement (animal side) ---------------------------------
    locomotion = metabolic_energy_tax(distance_km, elevation_gain_m, profile.body_mass_kg)
    # Locomotion mechanical energy is paid for out of metabolisable energy at the
    # activity efficiency, then scaled by the category demand factor.
    locomotion_me = (locomotion["total_mj"] / profile.activity_efficiency)
    maintenance_me = ME_MAINTENANCE_MJ_PER_KG075 * bw075 * profile.demand_factor
    me_required = maintenance_me + locomotion_me
    cp_required_g = CP_MAINTENANCE_G_PER_KG075 * bw075 * profile.demand_factor

    # --- Daily supply (range side) ---------------------------------------
    biomass = nutrition.biomass_kg_per_ha(ndvi) if ndvi is not None else None
    cp_pct = crude_protein_pct
    me_density = nutrition.forage_me_density(cp_pct) if cp_pct is not None else None
    avail = nutrition.availability_factor(vci, biomass)

    intake_kg = INTAKE_FRACTION_OF_BW * profile.body_mass_kg * avail
    me_supplied = intake_kg * me_density if me_density is not None else None
    cp_supplied_g = intake_kg * 1000.0 * (cp_pct / 100.0) if cp_pct is not None else None

    # --- Gaps -> supplementary feed --------------------------------------
    energy_gap_mj = (
        max(0.0, me_required - me_supplied) if me_supplied is not None else None
    )
    protein_gap_g = (
        max(0.0, cp_required_g - cp_supplied_g) if cp_supplied_g is not None else None
    )

    # Feed mass needed to close each gap independently, then the binding one.
    grams_for_energy = (
        (energy_gap_mj / profile.feed_block_me_mj_per_kg) * 1000.0
        if energy_gap_mj is not None
        else None
    )
    # FEED_BLOCK_CP_PCT% * 10 = g CP per kg of feed (e.g. 18% -> 180 g CP/kg).
    # protein_gap_g / (g CP per kg) gives kg of feed; * 1000 converts to grams.
    grams_for_protein = (
        (protein_gap_g / (FEED_BLOCK_CP_PCT * 10.0)) * 1000.0
        if protein_gap_g is not None
        else None
    )

    candidates = {
        "energy": grams_for_energy,
        "protein": grams_for_protein,
    }
    present = {k: v for k, v in candidates.items() if v is not None}
    if present:
        binding = max(present, key=present.get)
        feed_grams = round(present[binding], 1)
    else:
        binding = None
        feed_grams = None

    return {
        "species": profile.key,
        "species_label": profile.label,
        "body_mass_kg": profile.body_mass_kg,
        "requirement": {
            "maintenance_me_mj": round(maintenance_me, 3),
            "locomotion_me_mj": round(locomotion_me, 3),
            "total_me_mj": round(me_required, 3),
            "crude_protein_g": round(cp_required_g, 1),
        },
        "forage": {
            "biomass_kg_per_ha": biomass,
            "crude_protein_pct": cp_pct,
            "me_density_mj_per_kg": me_density,
            "availability_factor": avail,
            "intake_kg_per_day": round(intake_kg, 3),
            "me_supplied_mj": round(me_supplied, 3) if me_supplied is not None else None,
            "crude_protein_supplied_g": (
                round(cp_supplied_g, 1) if cp_supplied_g is not None else None
            ),
            "modeled": True,
        },
        "gaps": {
            "energy_mj": round(energy_gap_mj, 3) if energy_gap_mj is not None else None,
            "protein_g": round(protein_gap_g, 1) if protein_gap_g is not None else None,
            "grams_to_close_energy": (
                round(grams_for_energy, 1) if grams_for_energy is not None else None
            ),
            "grams_to_close_protein": (
                round(grams_for_protein, 1) if grams_for_protein is not None else None
            ),
        },
        "binding_constraint": binding,
        "supplementary_feed_grams": feed_grams,
        "locomotion_energy_mj": locomotion,
    }
