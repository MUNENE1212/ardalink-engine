"""ArdaLink Engine — FastAPI entrypoint.

Biophysical brain for satellite-to-pastoralist drought intelligence.
Owns the `gis_engine` Postgres schema and the GEE ingestion pipeline.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file at the repo root
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402

from ardalink_engine.src.api import grid_query  # noqa: E402
from ardalink_engine.src.api.assessment import ZonePairNotFound, run_assessment  # noqa: E402
from ardalink_engine.src.api.grid_query import GridNotBuilt  # noqa: E402
from ardalink_engine.src.api.models import (  # noqa: E402
    BuildGridRequest,
    JourneyRequest,
    PointConditionsRequest,
    ScheduleRunRequest,
    SpatialAssessmentRequest,
    SpatialAssessmentResponse,
)
from ardalink_engine.src.config import settings  # noqa: E402
from ardalink_engine.src.db.client import db_client  # noqa: E402
from ardalink_engine.src.db.schema import create_tables  # noqa: E402
from ardalink_engine.src.db.seed import seed_all  # noqa: E402
from ardalink_engine.src.logging_config import configure_logging, get_logger  # noqa: E402

configure_logging()
logger = get_logger("ardalink.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure the dedicated schema, tables, and seed data exist on startup."""
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)
    try:
        create_tables(db_client)
        counts = seed_all(db_client)
        logger.info("Engine ready. Table counts: %s", counts)
    except Exception as exc:  # surface startup DB issues clearly
        logger.exception("Engine startup failed during DB initialization: %s", exc)
        raise
    yield
    logger.info("Engine shutting down")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Biophysical engine — satellite ingestion, grid scoring, journey planning.",
    lifespan=lifespan,
)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


def run() -> None:
    import uvicorn

    host = os.environ.get("ARDALINK_HOST", "0.0.0.0")
    port = int(os.environ.get("ARDALINK_PORT", "5001"))
    uvicorn.run("ardalink_engine.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    run()