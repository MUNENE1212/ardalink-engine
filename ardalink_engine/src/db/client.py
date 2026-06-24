"""PostgreSQL client confined to the ``gis_engine`` schema namespace.

The engine shares the existing PostgreSQL instance with the core Node.js system
but must never read or write its tables. Every connection pins ``search_path`` to
the dedicated schema, and all DDL is schema-qualified, so the engine's actions are
contained within ``gis_engine``.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

import psycopg2
import psycopg2.extras

from ..config import settings
from ..logging_config import get_logger

logger = get_logger("ardalink.db")


class DatabaseClient:
    """Thin psycopg2 wrapper that scopes every action to a single schema."""

    def __init__(self, dsn: str | None = None, schema: str | None = None) -> None:
        self.dsn = dsn or settings.DATABASE_URL
        self.schema = schema or settings.DB_SCHEMA
        if not self.dsn:
            raise RuntimeError(
                "DATABASE_URL is not configured; the engine cannot connect to PostgreSQL."
            )

    @contextlib.contextmanager
    def connection(self) -> Iterator[psycopg2.extensions.connection]:
        """Yield a connection with ``search_path`` pinned to the engine schema."""
        conn = psycopg2.connect(self.dsn, options=f"-c search_path={self.schema}")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextlib.contextmanager
    def cursor(self) -> Iterator[psycopg2.extras.RealDictCursor]:
        """Yield a dict cursor within a managed connection."""
        with self.connection() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                yield cur
            finally:
                cur.close()

    def ensure_schema(self) -> None:
        """Create the dedicated schema if it does not already exist."""
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
        logger.info("Ensured schema '%s' exists", self.schema)

    def fetch_one(self, sql: str, params: tuple[Any, ...] | None = None) -> dict[str, Any] | None:
        with self.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None

    def fetch_all(self, sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
        with self.cursor() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)


db_client = DatabaseClient()
