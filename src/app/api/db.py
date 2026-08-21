"""Shared DB connection dependency for the API layer.

Reads DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME/DB_SSLMODE from the
environment (for production, e.g. the VPS deploy) and falls back to
src/app/config.py's creds_opendota for local dev (gitignored, not present
in production).
"""
from collections.abc import Iterator
import os

import psycopg
from psycopg_pool import ConnectionPool

try:
    from app.config import creds_opendota
except ImportError:
    creds_opendota = {}


def _conninfo() -> str:
    host = os.environ.get("DB_HOST", creds_opendota.get("host", ""))
    port = os.environ.get("DB_PORT", creds_opendota.get("port", ""))
    user = os.environ.get("DB_USER", creds_opendota.get("user", ""))
    password = os.environ.get("DB_PASSWORD", creds_opendota.get("pw", ""))
    dbname = os.environ.get("DB_NAME", creds_opendota.get("db", ""))
    sslmode = os.environ.get("DB_SSLMODE", creds_opendota.get("sslmode", "require"))
    if not all([host, user, dbname]):
        raise RuntimeError(
            "Database not configured: set DB_HOST/DB_USER/DB_PASSWORD/DB_NAME "
            "env vars, or provide src/app/config.py for local dev."
        )
    return f"host={host} port={port} user={user} password={password} dbname={dbname} sslmode={sslmode}"


pool = ConnectionPool(conninfo=_conninfo(), min_size=1, max_size=5, open=False)


def get_conn() -> Iterator[psycopg.Connection]:
    with pool.connection() as conn:
        yield conn
