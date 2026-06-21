"""Multi-tenant context helpers.

Every database operation in this service must be scoped to a tenant. The
contract is:

1. The HTTP request comes in with a verified JWT (validated by ardalink-api)
   that carries a `tenant_id` claim.
2. ardalink-api forwards the request to this service with the same `tenant_id`
   in an `X-Tenant-ID` header AND a signed attestation header (`X-Tenant-Sig`)
   so this service cannot be tricked into operating on a different tenant
   by an upstream bug.
3. This module exposes `set_tenant()` which issues the SQL
   `SET LOCAL app.current_tenant_id = '<id>'` on every connection obtained
   from the pool, before the caller's query runs.
4. Postgres RLS policies (see `migrations/0001_multitenant.up.sql`) then
   reject any row whose `tenant_id` does not match the session variable.

If a connection is used without `set_tenant()` having been called, every
scoped table returns zero rows. That is a deliberate fail-closed default.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from contextlib import contextmanager
from typing import Iterator

# The shared secret used to attest the X-Tenant-ID header. MUST match the
# secret in ardalink-api (`TENANT_ATTESTATION_SECRET` env var). When unset,
# attestation is disabled — only acceptable in local development.
def _tenant_attestation_secret() -> str:
    return os.environ.get("TENANT_ATTESTATION_SECRET", "")


def attest_tenant(tenant_id: str) -> str:
    """Compute the HMAC-SHA256 attestation for a tenant id.

    The same function runs on the ardalink-api side to mint the header.
    """
    secret = _tenant_attestation_secret()
    if not secret:
        return ""
    mac = hmac.new(
        secret.encode("utf-8"),
        tenant_id.encode("utf-8"),
        hashlib.sha256,
    )
    return mac.hexdigest()


def verify_tenant_attestation(tenant_id: str, attestation: str) -> bool:
    """Verify the HMAC-SHA256 attestation for a tenant id.

    In development (no shared secret configured), any non-empty tenant id
    passes. In production, set `TENANT_ATTESTATION_SECRET` and every request
    must carry a valid attestation.
    """
    secret = _tenant_attestation_secret()
    if not secret:
        return bool(tenant_id)
    expected = attest_tenant(tenant_id)
    return hmac.compare_digest(expected, attestation)


@contextmanager
def set_tenant(conn, tenant_id: str) -> Iterator[None]:
    """Bind a tenant to a database connection for the duration of a block.

    Issues `SET LOCAL app.current_tenant_id = '<id>'` so the Postgres session
    enforces RLS for every subsequent query on this connection.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    with conn.cursor() as cur:
        cur.execute("SET LOCAL app.current_tenant_id = %s", (tenant_id,))
    try:
        yield
    finally:
        # `SET LOCAL` reverts at transaction end. Nothing to undo here.
        pass