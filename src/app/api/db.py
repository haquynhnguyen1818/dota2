"""Shared DB connection dependency for the API layer.

Credential resolution lives in `app.credentials` -- environment first,
`src/app/config.py` second -- so the API and the ingestion loaders cannot drift
apart on where they read the database from.
"""
from collections.abc import Iterator

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg_pool import ConnectionPool

from app.credentials import db_kwargs

# make_conninfo quotes values properly; the hand-rolled f-string this replaced
# would have broken on a password containing a space.
pool = ConnectionPool(conninfo=make_conninfo(**db_kwargs()), min_size=1, max_size=5, open=False)


def get_conn() -> Iterator[psycopg.Connection]:
    with pool.connection() as conn:
        yield conn
