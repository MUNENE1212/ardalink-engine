"""Tests for ardalink_engine.src.geo.wards."""

from __future__ import annotations

import pytest

from ardalink_engine.src.geo.wards import WARDS, haversine_km


def test_haversine_zero_distance() -> None:
    assert haversine_km(0.355, 37.583, 0.355, 37.583) == pytest.approx(0.0, abs=1e-6)


def test_haversine_one_degree_latitude_is_about_111km() -> None:
    assert haversine_km(0.0, 0.0, 1.0, 0.0) == pytest.approx(111.19, rel=0.01)


def test_wards_contains_known_pilot_ward() -> None:
    keys_lower = [k.lower() for k in WARDS]
    assert any("bula" in k or "bulla" in k for k in keys_lower), (
        f"Expected a Bula/Bulla Pesa ward in WARDS registry, got: {list(WARDS)}"
    )


def test_wards_entries_have_required_fields() -> None:
    for name, ward in WARDS.items():
        assert hasattr(ward, "name"), f"{name} missing name"
        assert hasattr(ward, "latitude"), f"{name} missing latitude"
        assert hasattr(ward, "longitude"), f"{name} missing longitude"
        assert -90.0 <= ward.latitude <= 90.0
        assert -180.0 <= ward.longitude <= 180.0