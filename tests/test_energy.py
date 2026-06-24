"""Tests for ardalink_engine.src.core_math.energy.

The legacy API is function-based (no classes), so we test the actual
public functions: resolve_profile, assess_energy, assess_feed_gap.
"""

from __future__ import annotations

import math

import pytest

from ardalink_engine.src.core_math.energy import (
    assess_energy,
    assess_feed_gap,
    resolve_profile,
)


def test_resolve_profile_known_species() -> None:
    p = resolve_profile("cattle")
    assert p.key == "cattle"
    assert math.isfinite(p.body_mass_kg)


def test_resolve_profile_unknown_species_raises() -> None:
    with pytest.raises(ValueError, match="Unknown species"):
        resolve_profile("mythical-creature")


def test_assess_energy_returns_full_structure() -> None:
    result = assess_energy(distance_km=8.0, elevation_gain_m=10.0, species="cattle")
    assert result["species"] == "cattle"
    assert "energy" in result
    assert "total_mj" in result["energy"]
    assert "feed_recommendation_grams" in result
    assert "physiological_stress" in result
    assert 0.0 <= result["physiological_stress"] <= 1.0


def test_assess_energy_increases_with_distance() -> None:
    short = assess_energy(distance_km=4.0, elevation_gain_m=0.0, species="cattle")
    long = assess_energy(distance_km=20.0, elevation_gain_m=0.0, species="cattle")
    assert long["energy"]["total_mj"] > short["energy"]["total_mj"]


def test_assess_energy_elevation_increases_cost() -> None:
    flat = assess_energy(distance_km=10.0, elevation_gain_m=0.0, species="cattle")
    uphill = assess_energy(distance_km=10.0, elevation_gain_m=500.0, species="cattle")
    assert uphill["energy"]["total_mj"] > flat["energy"]["total_mj"]


def test_assess_feed_gap_returns_audit_block() -> None:
    result = assess_feed_gap(
        distance_km=8.0,
        elevation_gain_m=10.0,
        species="cattle",
        vci=0.45,
        ndvi=0.4,
        crude_protein_pct=6.0,
    )
    assert "forage" in result
    assert "gaps" in result
    assert "requirement" in result
    assert "supplementary_feed_grams" in result
    assert "binding_constraint" in result
    if result["supplementary_feed_grams"] is not None:
        assert isinstance(result["supplementary_feed_grams"], (int, float))
        assert result["supplementary_feed_grams"] >= 0