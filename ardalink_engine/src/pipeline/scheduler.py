"""In-process scheduler for county-wide batch ingestion of the grid layers.

The engine's map is only useful when every environmental layer is filled in over
the whole county and kept current. Running the ingestion endpoints by hand does
not scale, so this module drives them automatically on a sensible per-layer
cadence.

Design notes
------------
* **Durable freshness.** "Due" is decided from the persisted ``grid_layer_meta``
  ``updated_at`` timestamps (the same record :func:`grid_query._layer_freshness`
  exposes to the map), not from in-memory clocks. The schedule therefore survives
  restarts: a layer refreshed five minutes before a restart is not re-run.
* **One job at a time.** Earth Engine ``reduceRegions`` and the bulk DB writes
  are heavy, so only a single layer is ingested at once, in priority order
  (static first, then the dynamic layers). A cycle never overlaps itself.
* **Non-blocking.** The ingestion functions are synchronous and long-running
  (the full 250 m grid is ~2M cells), so each runs in a worker thread via
  :func:`asyncio.to_thread`; the event loop — and the engine's query endpoints —
  stay responsive throughout.
* **Visible failures.** Every attempt records its outcome (ok/error, duration,
  cells written, the error message) in memory and logs it. A failed layer leaves
  the previous data in place and is simply retried on the next due-check, rather
  than being silently abandoned.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..config import settings
from ..logging_config import get_logger
from . import grid_ingest

logger = get_logger("ardalink.pipeline.scheduler")


# Ordered ingestion plan: static terrain/envelope first (slowly changing), then
# the dynamic satellite/climate layers. Each entry maps a layer name to the
# callable that refreshes it county-wide and the configured cadence in hours.
def _ingest_static() -> dict:
    return grid_ingest.ingest_static()


def _ingest_layer(layer: str):
    def _run() -> dict:
        return grid_ingest.ingest_layer(layer)

    return _run


@dataclass
class _LayerJob:
    name: str
    run: callable
    interval_hours: float


def _build_plan() -> list[_LayerJob]:
    return [
        _LayerJob("static", _ingest_static, settings.INGEST_INTERVAL_STATIC_HOURS),
        _LayerJob("vegetation", _ingest_layer("vegetation"), settings.INGEST_INTERVAL_VEGETATION_HOURS),
        _LayerJob("protein", _ingest_layer("protein"), settings.INGEST_INTERVAL_PROTEIN_HOURS),
        _LayerJob("climate", _ingest_layer("climate"), settings.INGEST_INTERVAL_CLIMATE_HOURS),
        _LayerJob("soil", _ingest_layer("soil"), settings.INGEST_INTERVAL_SOIL_HOURS),
    ]


@dataclass
class _LayerStatus:
    """Live, in-memory record of a layer's scheduler history (this process)."""

    interval_hours: float
    last_started: str | None = None
    last_finished: str | None = None
    last_status: str | None = None  # "ok" | "error" | "running"
    last_error: str | None = None
    last_cells_written: int | None = None
    last_duration_s: float | None = None
    run_count: int = 0
    error_count: int = 0


@dataclass
class _SchedulerState:
    enabled: bool = False
    running_layer: str | None = None
    last_cycle_started: str | None = None
    last_cycle_finished: str | None = None
    cycle_count: int = 0
    layers: dict[str, _LayerStatus] = field(default_factory=dict)


_state = _SchedulerState()
_state_lock = threading.Lock()

# Single-flight guard: the background loop and the manual run-now endpoint both
# call _run_cycle(), so without this two cycles could overlap and ingest the same
# layer concurrently. That is wasteful (duplicate GEE/DB work) and, worse, lets
# vegetation compute VCI from a half-rewritten seasonal envelope while static is
# still mid-ingest. Only one cycle runs at a time; concurrent triggers are skipped.
_cycle_lock = asyncio.Lock()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _layer_meta() -> dict[str, dict]:
    """Map of layer name -> {updated_at, cells_written} from grid_layer_meta."""
    db = grid_ingest.db_client  # type: ignore[attr-defined]
    rows = db.fetch_all(
        f'SELECT layer, updated_at, cells_written FROM "{db.schema}".grid_layer_meta'
    )
    return {
        r["layer"]: {"updated_at": r["updated_at"], "cells_written": r["cells_written"]}
        for r in rows
    }


def _grid_cell_count() -> int:
    """Total cells in the built grid (0 if unbuilt)."""
    gm = grid_ingest.get_grid_meta()
    return int(gm["cell_count"]) if gm else 0


def _local_hour() -> float:
    """Current hour-of-day in the configured local timezone (UTC + offset)."""
    utc_hour = datetime.now(UTC).hour + datetime.now(UTC).minute / 60.0
    return (utc_hour + settings.INGEST_LOCAL_UTC_OFFSET_HOURS) % 24.0


def _in_night_window() -> bool:
    """True if scheduled ingests are allowed to run right now.

    Returns True when night-only gating is off, otherwise whether the current
    local hour falls in the [start, end) overnight window (which may wrap past
    midnight, e.g. 23 -> 5).
    """
    if not settings.INGEST_NIGHT_ONLY:
        return True
    start = settings.INGEST_NIGHT_START_HOUR
    end = settings.INGEST_NIGHT_END_HOUR
    hour = _local_hour()
    if start == end:
        return True  # degenerate window means "always"
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # wraps past midnight


def _envelope_month_stale() -> bool:
    """True when the stored seasonal NDVI envelope is for a different month.

    VCI is month-matched, so the static layer (which carries the envelope) must
    be re-ingested when the calendar month rolls over — even if its timestamp is
    still "fresh". NULL means it has never been computed seasonally yet.
    """
    gm = grid_ingest.get_grid_meta()
    if not gm:
        return False
    stored = gm.get("ndvi_envelope_month")
    return stored is None or int(stored) != datetime.now(UTC).month


def _due_reason(job: _LayerJob, meta: dict[str, dict], cell_count: int) -> str | None:
    """Why a layer is due now, or None if it is up to date.

    Three triggers: never ingested, under-covered (only ever ran over a small
    patch), or stale beyond its configured interval. Coverage is checked first so
    a partially-ingested layer is backfilled county-wide even if its timestamp is
    fresh.
    """
    row = meta.get(job.name)
    if row is None or row.get("updated_at") is None:
        return "never_ingested"
    written = row.get("cells_written") or 0
    if cell_count > 0 and written < settings.INGEST_MIN_COVERAGE_FRACTION * cell_count:
        return f"under_covered ({written}/{cell_count} cells)"
    age_hours = (datetime.now(UTC) - row["updated_at"]).total_seconds() / 3600.0
    if age_hours >= job.interval_hours:
        return f"stale ({age_hours:.1f}h ≥ {job.interval_hours:.0f}h)"
    # Static carries the month-matched NDVI envelope: refresh it when the
    # calendar month rolls over so VCI keeps comparing like-for-like season.
    if job.name == "static" and _envelope_month_stale():
        return "envelope_month_changed"
    return None


def _is_due(job: _LayerJob, meta: dict[str, dict], cell_count: int) -> bool:
    return _due_reason(job, meta, cell_count) is not None


def _run_one(job: _LayerJob) -> None:
    """Synchronously refresh a single layer, updating the in-memory status.

    Runs inside a worker thread (via ``asyncio.to_thread``). Exceptions are
    caught, logged at ERROR, and recorded — the previously ingested data is left
    untouched so the map keeps serving the last good values.
    """
    with _state_lock:
        st = _state.layers[job.name]
        st.last_started = _now_iso()
        st.last_status = "running"
        _state.running_layer = job.name

    logger.info("Scheduled ingest starting for layer '%s'", job.name)
    started = time.time()
    try:
        result = job.run()
        duration = time.time() - started
        with _state_lock:
            st = _state.layers[job.name]
            st.last_finished = _now_iso()
            st.last_status = "ok"
            st.last_error = None
            st.last_cells_written = int(result.get("cells_written", 0))
            st.last_duration_s = round(duration, 1)
            st.run_count += 1
        logger.info(
            "Scheduled ingest OK for layer '%s': %d cells in %.1fs",
            job.name, st.last_cells_written or 0, duration,
        )
    except Exception as exc:  # noqa: BLE001 - failures must stay visible, not crash the loop
        duration = time.time() - started
        with _state_lock:
            st = _state.layers[job.name]
            st.last_finished = _now_iso()
            st.last_status = "error"
            st.last_error = f"{type(exc).__name__}: {exc}"
            st.last_duration_s = round(duration, 1)
            st.error_count += 1
        logger.error(
            "Scheduled ingest FAILED for layer '%s' after %.1fs: %s",
            job.name, duration, exc, exc_info=True,
        )
    finally:
        with _state_lock:
            _state.running_layer = None


async def _run_cycle(force: bool, only: list[str] | None) -> None:
    """Run one due-check pass, ingesting each due layer one at a time.

    Guarded by ``_cycle_lock`` so the background loop and a manual run-now trigger
    can never overlap; a cycle requested while one is in flight is skipped.
    """
    if _cycle_lock.locked():
        logger.info("Scheduler cycle skipped: another ingest cycle is already running.")
        return
    async with _cycle_lock:
        await _run_cycle_locked(force, only)


async def _run_cycle_locked(force: bool, only: list[str] | None) -> None:
    if not settings.gee_configured:
        logger.warning("Scheduler cycle skipped: Earth Engine is not configured.")
        return
    if grid_ingest.get_grid_meta() is None:
        logger.warning("Scheduler cycle skipped: grid is not built yet (POST /api/v1/ingest/build-grid).")
        return
    # Scheduled (non-forced) ingests only run overnight; manual triggers bypass.
    if not force and not _in_night_window():
        logger.debug(
            "Scheduler cycle skipped: outside the overnight ingest window "
            "(local hour %.1f, window %02d:00-%02d:00).",
            _local_hour(), settings.INGEST_NIGHT_START_HOUR, settings.INGEST_NIGHT_END_HOUR,
        )
        return

    plan = _build_plan()
    if only is not None:
        wanted = set(only)
        plan = [j for j in plan if j.name in wanted]

    try:
        meta = _layer_meta()
        cell_count = _grid_cell_count()
    except Exception as exc:  # noqa: BLE001 - DB hiccup should not kill the loop
        logger.error("Scheduler cycle skipped: could not read layer freshness: %s", exc, exc_info=True)
        return

    due = []
    for job in plan:
        if force:
            due.append((job, "forced"))
            continue
        reason = _due_reason(job, meta, cell_count)
        if reason is not None:
            due.append((job, reason))
    if not due:
        logger.debug("Scheduler cycle: no layers due.")
        return

    with _state_lock:
        _state.last_cycle_started = _now_iso()
        _state.cycle_count += 1
    logger.info(
        "Scheduler cycle starting: %d layer(s) due (%s)",
        len(due), ", ".join(f"{j.name}: {r}" for j, r in due),
    )

    for job, _reason in due:
        # Each layer is heavy and synchronous — run it off the event loop so the
        # engine's query endpoints stay responsive during a multi-hour ingest.
        await asyncio.to_thread(_run_one, job)

    with _state_lock:
        _state.last_cycle_finished = _now_iso()
    logger.info("Scheduler cycle complete.")


async def _scheduler_loop() -> None:
    """Background loop: wait the startup grace period, then poll for due layers."""
    delay = settings.INGEST_STARTUP_DELAY_SECONDS
    if delay > 0:
        logger.info("Ingestion scheduler armed; first due-check in %.0fs.", delay)
        await asyncio.sleep(delay)
    while True:
        try:
            await _run_cycle(force=False, only=None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - never let the loop die silently
            logger.error("Scheduler loop iteration errored: %s", exc, exc_info=True)
        await asyncio.sleep(settings.INGEST_CHECK_INTERVAL_SECONDS)


# --------------------------------------------------------------------------
# Lifecycle (wired into the FastAPI lifespan in main.py)
# --------------------------------------------------------------------------
_task: asyncio.Task | None = None


def start() -> bool:
    """Start the background scheduler task. Returns True if it was started."""
    global _task
    plan = _build_plan()
    with _state_lock:
        _state.layers = {
            j.name: _LayerStatus(interval_hours=j.interval_hours) for j in plan
        }
        _state.enabled = settings.INGEST_SCHEDULER_ENABLED

    if not settings.INGEST_SCHEDULER_ENABLED:
        logger.info("Ingestion scheduler disabled (INGEST_SCHEDULER_ENABLED=0).")
        return False
    if not settings.gee_configured:
        logger.info("Ingestion scheduler not started: Earth Engine is not configured.")
        with _state_lock:
            _state.enabled = False
        return False

    _task = asyncio.create_task(_scheduler_loop())
    logger.info(
        "Ingestion scheduler started (intervals h: static=%.0f veg=%.0f protein=%.0f climate=%.0f soil=%.0f, "
        "check every %.0fs).",
        settings.INGEST_INTERVAL_STATIC_HOURS,
        settings.INGEST_INTERVAL_VEGETATION_HOURS,
        settings.INGEST_INTERVAL_PROTEIN_HOURS,
        settings.INGEST_INTERVAL_CLIMATE_HOURS,
        settings.INGEST_INTERVAL_SOIL_HOURS,
        settings.INGEST_CHECK_INTERVAL_SECONDS,
    )
    return True


async def stop() -> None:
    """Cancel the background scheduler task on shutdown."""
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    finally:
        _task = None
    logger.info("Ingestion scheduler stopped.")


async def trigger(force: bool = False, layers: list[str] | None = None) -> None:
    """Run a due-check cycle immediately (used by the manual run-now endpoint)."""
    await _run_cycle(force=force, only=layers)


def status() -> dict:
    """Snapshot of scheduler state + each layer's freshness and last outcome."""
    try:
        meta = _layer_meta()
    except Exception:  # noqa: BLE001 - status must never raise
        meta = {}
    cell_count = _grid_cell_count()
    plan = {j.name: j for j in _build_plan()}

    with _state_lock:
        running_layer = _state.running_layer
        layers_out: dict[str, dict] = {}
        for name, st in _state.layers.items():
            row = meta.get(name) or {}
            last_ingest = row.get("updated_at")
            cells_written = row.get("cells_written")
            next_due_iso = None
            if last_ingest is not None:
                next_due = last_ingest.timestamp() + st.interval_hours * 3600.0
                next_due_iso = datetime.fromtimestamp(next_due, tz=UTC).isoformat()
            job = plan.get(name)
            reason = _due_reason(job, meta, cell_count) if job is not None else None
            layers_out[name] = {
                "interval_hours": st.interval_hours,
                "last_ingested_at": last_ingest.isoformat() if last_ingest is not None else None,
                "cells_written": cells_written,
                "next_due_at": next_due_iso,
                "due_now": reason is not None,
                "due_reason": reason,
                "last_run_status": st.last_status,
                "last_run_started": st.last_started,
                "last_run_finished": st.last_finished,
                "last_run_error": st.last_error,
                "last_run_cells_written": st.last_cells_written,
                "last_run_duration_s": st.last_duration_s,
                "run_count": st.run_count,
                "error_count": st.error_count,
            }
        snapshot = {
            "enabled": _state.enabled,
            "earth_engine_configured": settings.gee_configured,
            "grid_built": grid_ingest.get_grid_meta() is not None,
            "running_layer": running_layer,
            "check_interval_seconds": settings.INGEST_CHECK_INTERVAL_SECONDS,
            "startup_delay_seconds": settings.INGEST_STARTUP_DELAY_SECONDS,
            "night_window": {
                "enabled": settings.INGEST_NIGHT_ONLY,
                "local_utc_offset_hours": settings.INGEST_LOCAL_UTC_OFFSET_HOURS,
                "start_hour": settings.INGEST_NIGHT_START_HOUR,
                "end_hour": settings.INGEST_NIGHT_END_HOUR,
                "local_hour_now": round(_local_hour(), 2),
                "open_now": _in_night_window(),
            },
            "cycle_count": _state.cycle_count,
            "last_cycle_started": _state.last_cycle_started,
            "last_cycle_finished": _state.last_cycle_finished,
            "layers": layers_out,
        }
    return snapshot
