"""Google Earth Engine initialization shared by the ingestion pipelines.

Server-to-server access uses a service account. Credentials are resolved from
the environment via :mod:`src.config` (``GEE_SERVICE_ACCOUNT`` + the JSON key in
``GEE_PRIVATE_KEY``). Initialization is lazy, thread-safe, and idempotent so the
API boots with zero GEE credentials and only touches Earth Engine on demand.
"""

from __future__ import annotations

import json
import re
import threading

from ..config import settings
from ..logging_config import get_logger

logger = get_logger("ardalink.pipeline.gee")

_initialized = False
_lock = threading.Lock()

# A Google Cloud project id is a plain slug, e.g. "tough-dreamer-484518-a0".
_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


class GEENotConfigured(RuntimeError):
    """Raised when Earth Engine is used without a configured service account."""


class GEEInitError(RuntimeError):
    """Raised when Earth Engine credentials are present but initialization fails."""


def _resolve_credentials() -> tuple[str, str, str]:
    """Resolve (service_account_email, project_id, key_data_json).

    The JSON service-account key is self-contained, so the email and project are
    derived from it. This is robust against the separate GEE_SERVICE_ACCOUNT /
    GEE_PROJECT secrets being filled with a display name or a Console URL. Those
    env vars are used only as fallbacks when the key lacks the field.
    """
    key_data = settings.GEE_PRIVATE_KEY
    if not key_data:
        raise GEENotConfigured(
            "Google Earth Engine is not configured (set GEE_PRIVATE_KEY to the "
            "service-account JSON key)."
        )

    email = settings.GEE_SERVICE_ACCOUNT
    project = settings.GEE_PROJECT
    try:
        parsed = json.loads(key_data)
    except (ValueError, TypeError):
        parsed = None

    if isinstance(parsed, dict):
        email = parsed.get("client_email") or email
        project = parsed.get("project_id") or project

    # Reject obviously-malformed project values (e.g. a pasted Console URL).
    if not project or not _PROJECT_ID_RE.match(project.strip()):
        raise GEEInitError(
            f"Could not determine a valid Google Cloud project id (got {project!r}). "
            "Provide the JSON service-account key (it contains project_id) or set "
            "GEE_PROJECT to the plain project id."
        )
    if not email or "@" not in email:
        raise GEEInitError(
            f"Could not determine the service-account email (got {email!r}). "
            "Provide the JSON service-account key (it contains client_email)."
        )
    return email.strip(), project.strip(), key_data


def ensure_initialized() -> None:
    """Initialize Earth Engine once, raising clear errors if it cannot."""
    global _initialized
    if _initialized:
        return
    with _lock:
        if _initialized:
            return
        email, project, key_data = _resolve_credentials()
        try:
            import ee  # lazy import — heavy dependency
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise GEEInitError("earthengine-api is not importable.") from exc
        try:
            credentials = ee.ServiceAccountCredentials(email, key_data=key_data)
            ee.Initialize(credentials, project=project)
            _initialized = True
            logger.info("Earth Engine initialized for project '%s'", project)
        except Exception as exc:
            raise GEEInitError(
                "Earth Engine initialization failed. Verify the service account, "
                "JSON key, and that the Earth Engine API is enabled on the project. "
                f"Underlying error: {exc}"
            ) from exc
