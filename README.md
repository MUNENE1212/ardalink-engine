<div align="center">

# ArdaLink Engine

### Biophysical brain for satellite-to-pastoralist drought intelligence

ArdaLink Engine ingests Earth observation data, scores livestock journeys,
and answers environmental questions for Isiolo County and beyond.

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-latest-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![uv](https://img.shields.io/badge/uv-package%20manager-DE5FE9)](https://docs.astral.sh/uv)
[![License](https://img.shields.io/badge/license-Proprietary-lightgrey)](#license)

</div>

---

## Quickstart

```bash
# Requires Python 3.12 and uv
uv sync
cp .env.example .env       # edit with your credentials

# Run the API
uv run uvicorn ardalink_engine.main:app --reload --port 5001

# Health check
curl http://localhost:5001/health
```

Open `http://localhost:5001/docs` for the interactive API.

---

## What this service does

| Capability | Endpoint |
|---|---|
| Point conditions (NDVI, NDRE, soil, climate) | `POST /api/v1/conditions` |
| Journey assessment (energy + nutrition scoring) | `POST /api/v1/journey` |
| Spatial assessment across a polygon | `POST /api/v1/spatial` |
| Grid build (Earth Engine reduceRegions) | `POST /api/v1/grid/build` |
| Schedule a refresh run | `POST /api/v1/schedule` |
| Health probe | `GET /health` |

See [`docs/01-ARCHITECTURE.md`](docs/01-ARCHITECTURE.md) for system context.

---

## Repository layout

```
ardalink-engine/
├── ardalink_engine/          # Python package (FastAPI app)
│   ├── main.py
│   ├── api/                  # route handlers + models
│   ├── core_math/            # energy + nutrition formulas
│   ├── db/                   # schema, seed, client
│   ├── geo/                  # grid + routing
│   ├── pipeline/             # GEE ingest, scheduler, obstacles
│   └── ai/                   # Azure OpenAI client
├── tests/                    # pytest (unit + integration + contract)
├── docs/                     # 8-doc CTO navigation
├── pyproject.toml
├── uv.lock
└── .env.example
```

---

## Documentation

Start with [`docs/00-EXECUTIVE-INDEX.md`](docs/00-EXECUTIVE-INDEX.md) (5 min).

---

## Sister repos

- [`MUNENE1212/ardalink-api`](https://github.com/MUNENE1212/ardalink-api) — voice, intelligence pipeline, ground-truth capture
- [`MUNENE1212/ardalink-web`](https://github.com/MUNENE1212/ardalink-web) — operator dashboard and public Talk app

---

## License

Proprietary — all rights reserved. Contact the maintainer before any reuse or distribution.