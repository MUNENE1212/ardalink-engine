"""Conftest for ardalink-engine tests.

Sets safe defaults for env vars so the FastAPI app can be imported and the
lifespan hook can run without crashing.
"""

from __future__ import annotations

import os

# Set defaults BEFORE any application import.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/ardalink_test")
os.environ.setdefault("GIS_ENGINE_SCHEMA", "gis_engine")
os.environ.setdefault("ARDALINK_LOG_LEVEL", "WARNING")
os.environ.setdefault("TENANT_ATTESTATION_SECRET", "test-attestation-secret-32-chars-min")
os.environ.setdefault("GEE_SERVICE_ACCOUNT", "test@project.iam.gserviceaccount.com")
os.environ.setdefault("GEE_PROJECT", "test-project")
os.environ.setdefault("INGEST_SCHEDULER_ENABLED", "0")