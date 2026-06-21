"""Smoke tests for the FastAPI app (no DB calls)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ardalink_engine.main import app


def test_health_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body