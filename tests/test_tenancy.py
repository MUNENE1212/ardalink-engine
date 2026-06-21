"""Tests for multi-tenant context helpers."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from ardalink_engine.tenancy import attest_tenant, set_tenant, verify_tenant_attestation


def test_set_tenant_rejects_empty() -> None:
    """An empty tenant id must be rejected, not silently coerced."""
    conn = MagicMock()
    with pytest.raises(ValueError, match="tenant_id is required"):
        with set_tenant(conn, ""):
            pass


def test_set_tenant_executes_set_local() -> None:
    """The SQL `SET LOCAL` must be issued with the supplied tenant id."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    with set_tenant(conn, "bula-pesa"):
        pass
    cursor.execute.assert_called_once_with(
        "SET LOCAL app.current_tenant_id = %s", ("bula-pesa",)
    )


def test_attestation_round_trip() -> None:
    """Attestation produced by `attest_tenant` must verify, and a tampered id must not."""
    os.environ["TENANT_ATTESTATION_SECRET"] = "test-secret-do-not-use-in-prod"
    import importlib

    import ardalink_engine.tenancy as tenancy_mod

    importlib.reload(tenancy_mod)

    sig = tenancy_mod.attest_tenant("bula-pesa")
    assert tenancy_mod.verify_tenant_attestation("bula-pesa", sig) is True
    assert tenancy_mod.verify_tenant_attestation("garbatulla", sig) is False
    assert tenancy_mod.verify_tenant_attestation("bula-pesa", "tampered") is False

    del os.environ["TENANT_ATTESTATION_SECRET"]
    importlib.reload(tenancy_mod)


def test_attestation_skipped_when_secret_unset() -> None:
    """In dev (no secret), any non-empty tenant id passes attestation."""
    assert verify_tenant_attestation("bula-pesa", "any-or-none") is True
    assert verify_tenant_attestation("", "any") is False