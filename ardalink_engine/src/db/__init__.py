"""Database access layer, restricted to the dedicated GIS engine schema."""

from .client import DatabaseClient, db_client

__all__ = ["DatabaseClient", "db_client"]
