"""Central configuration for the ArdaLink Biophysical Data Engine.

All settings are sourced from environment variables so the engine stays a clean,
portable B2B data asset with zero hard-coded credentials.
"""

from __future__ import annotations

import os


class Settings:
    """Runtime settings resolved from the environment."""

    # --- Application ---------------------------------------------------------
    APP_NAME: str = "ArdaLink Biophysical Data Engine"
    APP_VERSION: str = "1.0.0"
    HOST: str = os.getenv("ARDALINK_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("ARDALINK_PORT", os.getenv("PORT", "5001")))
    LOG_LEVEL: str = os.getenv("ARDALINK_LOG_LEVEL", "INFO")

    # --- Database -----------------------------------------------------------
    # We connect to the existing PostgreSQL instance but restrict every action
    # to a dedicated schema namespace so the engine never touches the
    # user-facing Node.js system's tables.
    DATABASE_URL: str | None = os.getenv("DATABASE_URL")
    DB_SCHEMA: str = os.getenv("GIS_ENGINE_SCHEMA", "gis_engine")

    # --- Geospatial routing (obstacle avoidance) ----------------------------
    # Bounding box of Isiolo County (south, west, north, east) used to query
    # publicly mapped protected areas / conservancies to route livestock around.
    ISIOLO_BBOX: tuple[float, float, float, float] = (
        float(os.getenv("ISIOLO_BBOX_S", "-0.6")),
        float(os.getenv("ISIOLO_BBOX_W", "36.5")),
        float(os.getenv("ISIOLO_BBOX_N", "2.9")),
        float(os.getenv("ISIOLO_BBOX_E", "39.6")),
    )
    OVERPASS_URL: str = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
    OVERPASS_TIMEOUT_SECONDS: float = float(os.getenv("OVERPASS_TIMEOUT_SECONDS", "90"))
    OBSTACLE_CACHE_TTL_SECONDS: float = float(os.getenv("OBSTACLE_CACHE_TTL_SECONDS", "21600"))

    # --- Pre-computed environmental grid -----------------------------------
    # All environmental layers are ingested into a regular grid over the Isiolo
    # bounding box and stored in Postgres, so live queries are cheap nearest-cell
    # lookups instead of per-request Earth Engine calls. The grid is a regular
    # lat/lon lattice, so the nearest cell to any point is pure arithmetic (no
    # PostGIS / KNN needed). Default cell size is 250 m (the production target);
    # set coarser for cheap validation. Grid build/ingestion is on-demand only.
    GRID_RESOLUTION_M: float = float(os.getenv("GRID_RESOLUTION_M", "250"))
    # Cells per Earth Engine reduceRegions getInfo call (respect feature limits).
    GRID_CHUNK_SIZE: int = int(os.getenv("GRID_CHUNK_SIZE", "2000"))

    # --- Scheduled batch ingestion ------------------------------------------
    # An in-process scheduler refreshes the grid layers county-wide on a sensible
    # cadence so the map stays current without manual ops. It uses the persisted
    # ``grid_layer_meta`` freshness timestamps to decide what is due (so it is
    # correct across restarts), runs one layer at a time in a worker thread, and
    # logs every attempt/failure. Disabled automatically when GEE is unconfigured
    # or the grid is not built. Set INGEST_SCHEDULER_ENABLED=0 to turn it off.
    INGEST_SCHEDULER_ENABLED: bool = os.getenv("INGEST_SCHEDULER_ENABLED", "1").lower() not in (
        "0", "false", "no", "off",
    )
    # How often the scheduler wakes to check which layers are due (seconds).
    INGEST_CHECK_INTERVAL_SECONDS: float = float(
        os.getenv("INGEST_CHECK_INTERVAL_SECONDS", "900")
    )
    # Grace period after startup before the first due-check, so frequent restarts
    # do not immediately kick off a heavy county-wide ingest (seconds).
    INGEST_STARTUP_DELAY_SECONDS: float = float(
        os.getenv("INGEST_STARTUP_DELAY_SECONDS", "120")
    )
    # Per-layer refresh cadence (hours). Defaults track each product's real-world
    # update frequency: terrain/NDVI-envelope/urban change slowly (weekly); the
    # measured climate/soil products update daily; vegetation/protein every couple
    # of days. A layer is "due" when now - updated_at exceeds its interval (or it
    # has never been ingested).
    # A layer is also considered due (regardless of freshness) when its stored
    # county-wide coverage is below this fraction of the grid — this backfills
    # layers that were only ever ingested over a small test patch. Cloud/edge
    # masking means a full ingest rarely writes 100% of cells, so the default is
    # deliberately well below 1.0; raise toward 1.0 to demand near-total coverage.
    INGEST_MIN_COVERAGE_FRACTION: float = float(
        os.getenv("INGEST_MIN_COVERAGE_FRACTION", "0.5")
    )
    # Defaults are weekly: the satellites themselves do not pass daily (Sentinel-2
    # ~5-day revisit, MODIS MOD13Q1 a 16-day composite), so a daily refresh mostly
    # re-pulls unchanged imagery and burns GEE quota for nothing. Weekly keeps the
    # map current with the real cadence of new observations. Override per-layer via
    # env if a faster cadence is ever wanted.
    INGEST_INTERVAL_STATIC_HOURS: float = float(os.getenv("INGEST_INTERVAL_STATIC_HOURS", "168"))
    INGEST_INTERVAL_VEGETATION_HOURS: float = float(
        os.getenv("INGEST_INTERVAL_VEGETATION_HOURS", "168")
    )
    INGEST_INTERVAL_PROTEIN_HOURS: float = float(os.getenv("INGEST_INTERVAL_PROTEIN_HOURS", "168"))
    INGEST_INTERVAL_CLIMATE_HOURS: float = float(os.getenv("INGEST_INTERVAL_CLIMATE_HOURS", "168"))
    INGEST_INTERVAL_SOIL_HOURS: float = float(os.getenv("INGEST_INTERVAL_SOIL_HOURS", "168"))

    # Run scheduled ingests only during a quiet overnight window (local time). The
    # heavy county-wide GEE reductions and bulk DB writes then land when the map is
    # least used. Manual triggers (POST /ingest/schedule/run) bypass this window.
    # Isiolo, Kenya is East Africa Time = UTC+3 (no DST), so local hour is computed
    # as UTC + INGEST_LOCAL_UTC_OFFSET_HOURS. The window is [start, end) and may
    # wrap past midnight (e.g. start 23, end 5).
    INGEST_NIGHT_ONLY: bool = os.getenv("INGEST_NIGHT_ONLY", "1").lower() not in (
        "0", "false", "no", "off",
    )
    INGEST_LOCAL_UTC_OFFSET_HOURS: float = float(
        os.getenv("INGEST_LOCAL_UTC_OFFSET_HOURS", "3")
    )
    INGEST_NIGHT_START_HOUR: int = int(os.getenv("INGEST_NIGHT_START_HOUR", "1"))
    INGEST_NIGHT_END_HOUR: int = int(os.getenv("INGEST_NIGHT_END_HOUR", "5"))

    # --- Google Earth Engine (live satellite + DEM) -------------------------
    # Server-to-server access uses a service account. The JSON key contents
    # (GEE_PRIVATE_KEY) are the primary, self-contained credential: the account
    # email and Cloud project are derived from it. GEE_SERVICE_ACCOUNT / GEE_PROJECT
    # are optional fallbacks only (and are ignored when present in the key).
    GEE_SERVICE_ACCOUNT: str | None = os.getenv("GEE_SERVICE_ACCOUNT")
    GEE_PRIVATE_KEY: str | None = os.getenv("GEE_PRIVATE_KEY")
    GEE_PROJECT: str | None = os.getenv("GEE_PROJECT")

    @property
    def gee_configured(self) -> bool:
        """True when an Earth Engine credential is available (JSON key required)."""
        return bool(self.GEE_PRIVATE_KEY)

    # --- Azure OpenAI (credit optimization) ---------------------------------
    # Heavy AI analytical tasks are routed to hosted Azure GPT-4o instances.
    AZURE_OPENAI_ENDPOINT: str | None = os.getenv("AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_KEY: str | None = os.getenv("AZURE_OPENAI_KEY")
    AZURE_OPENAI_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    AZURE_OPENAI_API_VERSION: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")
    AZURE_OPENAI_TIMEOUT_SECONDS: float = float(os.getenv("AZURE_OPENAI_TIMEOUT_SECONDS", "30"))

    @property
    def azure_configured(self) -> bool:
        """True when both Azure endpoint and key are present."""
        return bool(self.AZURE_OPENAI_ENDPOINT and self.AZURE_OPENAI_KEY)


settings = Settings()
