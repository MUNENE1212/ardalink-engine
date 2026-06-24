"""Forage quantity and quality models for Isiolo rangelands.

The supplementary-feed recommendation depends on two things the animal's grazing
cannot be assumed to supply:

* **Quantity** — how much dry forage biomass is on the ground, estimated from
  greenness (NDVI). This caps how much an animal can physically harvest.
* **Quality** — the crude-protein concentration of that forage, estimated from
  the red-edge index (NDRE). Protein, not bulk, is usually the binding
  constraint on dry-season rangelands.

Both are **transparent, uncalibrated proxies**: simple published-form regressions
on the satellite indices, not field-calibrated equations for Isiolo. Every value
derived here is labelled as ``modeled`` so downstream consumers never mistake it
for ground truth. The coefficients are chosen to span agronomically plausible
ranges and are isolated here so they can be recalibrated against field cuttings
when such data exists.
"""

from __future__ import annotations

# --- Biomass (quantity) from NDVI ------------------------------------------
# Standing dry-matter biomass rises roughly linearly with NDVI above a bare-soil
# floor. Coefficients give ~0 kg DM/ha at the floor and ~1.6 t/ha at NDVI 0.5,
# a plausible envelope for semi-arid rangeland. Labelled as a modeled proxy.
NDVI_BARE_SOIL = 0.10
BIOMASS_KG_PER_HA_PER_NDVI = 4000.0
BIOMASS_CEILING_KG_PER_HA = 5000.0

# --- Crude protein (quality) from NDRE -------------------------------------
# Canopy nitrogen (and therefore crude protein = N x 6.25) correlates with the
# red-edge index. A linear NDRE->CP% form is used, clamped to the range seen on
# tropical rangelands (dry standing hay ~3% up to lush green flush ~18%).
CP_INTERCEPT_PCT = 2.0
CP_SLOPE_PCT_PER_NDRE = 30.0
CP_MIN_PCT = 3.0
CP_MAX_PCT = 18.0

# Metabolisable energy density of forage (MJ/kg DM) as a function of crude
# protein — higher-protein green forage is also more digestible/energy-dense.
# Spans poor dry standing hay (~6) to green flush (~11).
FORAGE_ME_INTERCEPT = 5.5
FORAGE_ME_SLOPE_PER_CP = 0.35
FORAGE_ME_MIN = 6.0
FORAGE_ME_MAX = 11.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def biomass_kg_per_ha(ndvi: float) -> float:
    """Estimate standing dry-matter biomass (kg DM/ha) from NDVI. Modeled proxy."""
    raw = BIOMASS_KG_PER_HA_PER_NDVI * (ndvi - NDVI_BARE_SOIL)
    return round(_clamp(raw, 0.0, BIOMASS_CEILING_KG_PER_HA), 1)


def crude_protein_pct(ndre: float) -> float:
    """Estimate forage crude-protein concentration (% of DM) from NDRE.

    CP% = clamp(intercept + slope * NDRE). Derived as canopy N x 6.25 in the
    underlying regression form. Modeled proxy — not field-calibrated.
    """
    raw = CP_INTERCEPT_PCT + CP_SLOPE_PCT_PER_NDRE * ndre
    return round(_clamp(raw, CP_MIN_PCT, CP_MAX_PCT), 1)


def forage_me_density(crude_protein_percent: float) -> float:
    """Metabolisable energy density of forage (MJ/kg DM) from crude protein."""
    raw = FORAGE_ME_INTERCEPT + FORAGE_ME_SLOPE_PER_CP * crude_protein_percent
    return round(_clamp(raw, FORAGE_ME_MIN, FORAGE_ME_MAX), 2)


def availability_factor(vci: float | None, biomass: float | None) -> float:
    """Fraction (0-1) of potential intake the range can actually supply.

    Driven by whichever scarcity signal is available: a low Vegetation Condition
    Index (drought relative to history) or low standing biomass both throttle how
    much an animal can harvest in a day. Returns 1.0 (no throttle) when neither
    signal is available, so the caller's status flags carry the uncertainty.
    """
    factors: list[float] = []
    if vci is not None:
        # Full intake by ~VCI 60; linear throttle below that.
        factors.append(_clamp(vci / 60.0, 0.1, 1.0))
    if biomass is not None:
        # Full intake by ~1200 kg DM/ha standing biomass.
        factors.append(_clamp(biomass / 1200.0, 0.1, 1.0))
    if not factors:
        return 1.0
    return round(min(factors), 3)


# --- Drought interpretation -------------------------------------------------
# Vegetation Condition Index drought classes (VCI = where current greenness sits
# between its long-run min and max). Standard agricultural-drought severity bands.
def drought_status(vci: float | None) -> str | None:
    """Classify drought severity from VCI. Returns None when VCI is unavailable."""
    if vci is None:
        return None
    if vci < 10:
        return "extreme"
    if vci < 20:
        return "severe"
    if vci < 35:
        return "moderate"
    if vci < 50:
        return "mild"
    return "none"
