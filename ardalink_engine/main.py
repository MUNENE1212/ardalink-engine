"""ArdaLink Engine — FastAPI entrypoint.

Skeleton v0.1.0 — full source migrated in Phase 3 from
`biophysical-engine/ardalink-engine/`.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from pydantic import BaseModel

__version__ = "0.1.0"


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


def create_app() -> FastAPI:
    app = FastAPI(
        title="ArdaLink Engine",
        version=__version__,
        description="Biophysical brain for satellite-to-pastoralist drought intelligence.",
    )

    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service="ardalink-engine", version=__version__)

    return app


app = create_app()


def run() -> None:
    import uvicorn

    host = os.environ.get("ARDALINK_HOST", "0.0.0.0")
    port = int(os.environ.get("ARDALINK_PORT", "5001"))
    uvicorn.run("ardalink_engine.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    run()